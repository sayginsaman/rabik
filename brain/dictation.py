"""Dictation cleanup: the transcript the model tidies, the user's spellings as hints, and the fallback."""
import atexit
import difflib
import json
import os
import re
import signal
import sys
import threading
import unicodedata
from functools import lru_cache
from brain import clients, meeting, memory, prefs, prompts

__all__ = ['DICTATE_WORD', 'DICTATE_FILLER', 'DICTATE_DISCOURSE', 'dictate_words', 'DICTATE_MERGE', 'dictate_sound',
           'dictate_distance', 'dictate_sounds', 'dictate_hints', 'dictate_spellings', 'dictate_request', 'dictate_fallback',
           'dictate_chunks', 'dictate_result', 'dictate_cleanup', 'dictate_warmed', 'dictate_cleanup_wait']


DICTATE_WORD = re.compile(r"[\w]+(?:['’.-][\w]+)*", re.UNICODE)


DICTATE_FILLER = re.compile(r'(?i)\b(?:um+|uh+|ah+|eh+|erm+|euh+)\b\s*,?\s*')


DICTATE_DISCOURSE = re.compile(r'(?i)(?:,\s*(?:like|you know)\s*)+,\s*')


def dictate_words():
    words = prefs.pref('dictateWords', [])
    return [w for w in words if isinstance(w, str) and 0 < len(w) <= 80 and not any(ord(c) < 32 for c in w)][:500] if isinstance(words, list) else []


DICTATE_MERGE = str.maketrans('dbfvngcqzx', 'tpppmkkkss')


@lru_cache(maxsize=4096)
def dictate_sound(text):
    """How a word sounds, roughly (same rule as DictationData.sound): "Saarth", "Sarda", "sort" → "srt"."""
    s = ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if c.isalpha())
    for a, b in (('ph', 'f'), ('th', 't'), ('ck', 'k'), ('sh', 's'), ('qu', 'k')):
        s = s.replace(a, b)
    out = ''
    for i, c in enumerate(s):
        k = ('a' if i == 0 else '') if c in 'aeiouyhw' else c.translate(DICTATE_MERGE)
        if k and not out.endswith(k):
            out += k
    return out


def dictate_distance(a, b):
    row = list(range(len(b) + 1))
    for i, c in enumerate(a, 1):
        nxt = [i]
        for j, d in enumerate(b, 1):
            nxt.append(min(nxt[j - 1] + 1, row[j] + 1, row[j - 1] + (c != d)))
        row = nxt
    return row[-1]


def dictate_sounds(a, b):
    x, y = dictate_sound(a), dictate_sound(b)
    return len(x) >= 2 and x[:1] == y[:1] and (x == y or min(len(x), len(y)) >= 3 and abs(len(x) - len(y)) <= 1 and dictate_distance(x, y) <= 1)


def dictate_hints(text, words):
    """Heard words that may be a dictionary word: learned heard forms, else sound-alikes. The model decides from context."""
    fixes = prefs.pref('dictateFixes', {})
    fixes = {k: v for k, v in fixes.items() if isinstance(k, str) and v in words} if isinstance(fixes, dict) else {}
    heard = DICTATE_WORD.findall(text)
    spans = heard + [f'{a} {b}' for a, b in zip(heard, heard[1:])] + [f'{a} {b} {c}' for a, b, c in zip(heard, heard[1:], heard[2:])]
    present = {s.casefold() for s in spans}
    sounds = {w: dictate_sound(w) for w in words}
    by_sound = {}   # first sound → words not already said right
    for w in words:
        if w.casefold() not in present and ' ' not in w:
            by_sound.setdefault(sounds[w][:1], []).append(w)
    hints, matches = {}, {}
    for span in spans:
        if len(hints) >= 20:
            break
        sound = dictate_sound(span)
        near = (lambda w: sound == sounds[w]) if ' ' in span else (lambda w: len(sound) >= 2 and sound[:1] == sounds[w][:1] and
                (sound == sounds[w] or min(len(sound), len(sounds[w])) >= 3 and abs(len(sound) - len(sounds[w])) <= 1 and
                 dictate_distance(sound, sounds[w]) <= 1))   # several words: only an exact sound or a learned fix
        key = sound, ' ' in span
        if key not in matches: matches[key] = next((w for w in by_sound.get(sound[:1], []) if near(w)), None)
        word = fixes.get(span.casefold()) or matches[key]
        if word and word.casefold() not in present:
            hints.setdefault(span, word)
    return hints


def dictate_spellings(text, hints=None):
    # Keep 1.3.1's free-form saved spelling rules alongside the explicit dictionary.
    words = dictate_words()
    hints = dictate_hints(text, words) if hints is None and words else hints or {}
    return (('Dictionary spellings (data): ' + json.dumps(words, ensure_ascii=False) + '\n' if words else '') +
            ('May be a misheard dictionary word (data; heard → word; use it only where it fits the sentence, as a name or term would): ' +
             json.dumps(hints, ensure_ascii=False) + '\n' if hints else '') + memory.relevant_rules(text)[:1000])


def dictate_request(text, corrections=None):
    corrections = dictate_spellings(text) if corrections is None else corrections
    saved = ('Names and terms (data; use only to spell or fix heard words):\n' + corrections + '\n') if corrections else ''
    return saved + '<dictation>\n' + json.dumps(text, ensure_ascii=False) + '\n</dictation>'


def dictate_fallback(text):
    """Local safety path: remove only unmistakable fillers."""
    return DICTATE_DISCOURSE.sub(' ', DICTATE_FILLER.sub('', text)).strip()


def dictate_chunks(text, limit=6000):
    """Bound model input without truncating long dictation."""
    text, chunks = str(text), []
    while len(text) > limit:
        boundaries = [m.end() for m in re.finditer(r'(?:\n\s*\n|[.!?](?:\s+|$)|\s+)', text[:limit + 1])]
        cut = boundaries[-1] if boundaries and boundaries[-1] >= limit // 2 else limit
        piece, rest = text[:cut].rstrip(), text[cut:]
        whitespace = text[len(piece):cut] + rest[:len(rest) - len(rest.lstrip())]
        separator = '\n\n' if whitespace.count('\n') > 1 else ' ' if whitespace else ''
        chunks.append((piece, separator))
        text = rest.lstrip()
    if text.strip():
        chunks.append((text.strip(), ''))
    return chunks


def dictate_result(text, output, hints=None):
    match = re.fullmatch(r'\s*<cleaned>(.*)</cleaned>\s*', output, re.DOTALL)
    if not match:
        return dictate_fallback(text)
    cleaned = match.group(1).strip()
    if len(cleaned) > 1 and cleaned[0] in '"“' and cleaned[-1] in '"”' and text.strip()[:1] not in '"“':
        cleaned = cleaned[1:-1].strip()   # the model quoted the whole transcript
    source_words = DICTATE_WORD.findall(text.casefold().replace('’', "'"))
    comparable = re.sub(r'(?m)^\s*(?:[-*•]|\d+[.)])\s+', '', cleaned)
    output_words = DICTATE_WORD.findall(comparable.casefold().replace('’', "'"))
    heard = set(source_words) | {a + b for a, b in zip(source_words, source_words[1:])}   # "for get" → "forget"
    dictionary = set(DICTATE_WORD.findall(' '.join((hints or {}).values()).casefold()))   # only this chunk's heard → dictionary hints
    consonants = lambda w: re.sub(r'[aeiouy]', '', w)
    negations = lambda words, no=True: sum(w in ('not', 'never', 'cannot') or w.endswith("n't") or no and w == 'no' for w in words)
    cut = len(output_words) * 2 <= len(source_words)   # dropping half is a scratch-that or repair: it reuses heard words as they were
    spoken = DICTATE_WORD.findall(dictate_fallback(text).casefold().replace('’', "'"))   # a dropped filler is no edit
    edits = [(i1, i2, j1, j2) for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, spoken, output_words).get_opcodes() if tag != 'equal' and i1 != i2]
    tail_cut = bool(edits) and edits[-1][1] == len(spoken) and edits[-1][2] == edits[-1][3]   # a restart re-says the ending; a deleted ending is a dropped thought
    # An abandoned try opens like its replacement or shares a phrase or real word with it ("by this window… by this Friday"); an extract drops words never re-said.
    def resaid(i1, i2, j1, j2):
        near = output_words[max(0, j1 - 6):j2 + 6]
        return (output_words[j2:j2 + 1] == spoken[i1:i1 + 1] or any(len(w) > 3 and w in near for w in spoken[i1:i2]) or
                bool(set(zip(spoken[i1:i2], spoken[i1 + 1:i2])) & set(zip(near, near[1:]))))
    unsaid = sum(i2 - i1 - (j2 - j1) for i1, i2, j1, j2 in edits if not resaid(i1, i2, j1, j2))
    def familiar(word):
        stem, _, tail = word.partition("'")
        if word in heard or tail not in ('', 't') and stem in heard: return True   # "it'" → "it'll"
        if re.fullmatch(r'\d+(?:\.\d+)?', word): return True   # spoken numbers in any language become digits: "cinco dólares" → "$5"
        if word in dictionary: return True   # "start to" → "Saarth": a name the recognizer never spells
        if cut: return False
        threshold = .65
        # Misheard words sound alike: "get bad" → "GitHub" keeps its consonants.
        return len(word) >= 3 and any(difflib.SequenceMatcher(None, word, old).ratio() >= threshold or len(consonants(word)) >= 3 and
                                      difflib.SequenceMatcher(None, consonants(word), consonants(old)).ratio() >= .75 for old in heard)
    # A compliant answer usually adds words or collapses an instruction to its requested payload.
    room = 0 if cut else len(source_words) // 8   # a grammar fix may add a short word: "talk it" → "talk to it"
    dropped = negations(source_words, False) - negations(output_words, False)   # fine with its clause (a false start), never in place
    new = [w for w in output_words if not familiar(w)]
    respelled = 0 if cut else len(source_words) // 12   # misheard terms with no sound-alike ("Whisperflow" → "Wispr Flow"); an answer adds many
    if (not output_words or len(output_words) > len(source_words) + room or
            negations(output_words) > negations(source_words) or   # a fix never flips meaning; "no wait" is a repair cue
            dropped > 0 and dropped * 2 > len(source_words) - len(output_words) or
            len(output_words) * 3 < len(source_words) or   # "scratch that" can drop more than half; under a third is an extracted payload
            cut and (tail_cut or unsaid > max(3, len(spoken) // 6)) or   # a restart drops re-said tries; dropping words never re-said is an extract
            unsaid > max(8, len(spoken) // 6) or   # spoken punctuation and fillers drop a few words; a dropped sentence is a summary
            len(new) > room + respelled or sum(len(w) > 3 for w in new) > respelled):
        return dictate_fallback(text)
    return dictate_fallback(cleaned)


def dictate_cleanup(text):
    """Tool-free Cheapest-model edits; long speech is chunked instead of truncated."""
    chunks = dictate_chunks(text)
    if not chunks:
        return ''
    if prefs.client() != 'claude' or len(DICTATE_WORD.findall(text)) < 3:   # a word or two has nothing to clean
        return ''.join(dictate_fallback(chunk) + separator for chunk, separator in chunks).rstrip()
    cleaned = []
    for chunk, separator in chunks:
        hints = dictate_hints(chunk, dictate_words())
        corrections = dictate_spellings(chunk, hints)
        try:
            output, _ = meeting.meeting_call(prompts.DICTATE_SYSTEM, dictate_request(chunk, corrections),
                                     model='haiku', label='Dictation cleanup')
            cleaned.append((dictate_result(chunk, output, hints), separator))
        except Exception:
            cleaned.append((dictate_fallback(chunk), separator))
    return ''.join(value + separator for value, separator in cleaned).rstrip()


def dictate_warmed(p, text, corrections, hints=None):
    p.stdin.write(meeting.meeting_payload(dictate_request(text, corrections)))
    p.stdin.close()
    full = ''
    for line in p.stdout:
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict):
            continue
        event = row.get('event')
        event = event if isinstance(event, dict) else {}
        if row.get('type') == 'stream_event' and event.get('type') == 'content_block_delta':
            delta = event.get('delta')
            text_delta = delta.get('text') if isinstance(delta, dict) else None
            if isinstance(text_delta, str):
                full += text_delta
            if '</cleaned>' in full:
                return dictate_result(text, full, hints)
        if row.get('type') == 'result':
            if row.get('is_error'):
                raise RuntimeError('Could not clean up')
            if isinstance(row.get('result'), str):
                return dictate_result(text, row['result'], hints)
    raise RuntimeError('Could not clean up')


def dictate_cleanup_wait():
    """Start Claude before key-up, then accept one transcript on stdin (optionally: text before the cursor, NUL, transcript)."""
    if prefs.client() != 'claude':
        return print(dictate_fallback(sys.stdin.read().rpartition('\0')[2]), flush=True)
    try:
        p = meeting.meeting_process(prompts.DICTATE_SYSTEM, 'haiku')
    except Exception:
        return print(dictate_fallback(sys.stdin.read().rpartition('\0')[2]), flush=True)
    atexit.register(clients.stop_claude, p)
    signal.signal(signal.SIGTERM, lambda *_: (clients.stop_claude(p), sys.exit(0)))
    deadline, expired = None, threading.Event()
    def expire():
        expired.set()
        clients.stop_claude(p)
    try:
        before, _, text = sys.stdin.read().rpartition('\0')
        chunks = dictate_chunks(text)
        if len(DICTATE_WORD.findall(text)) < 3:
            return print(''.join(dictate_fallback(chunk) + separator for chunk, separator in chunks).rstrip(), flush=True)
        first, first_separator = chunks[0]
        before = before[-600:].strip()
        deadline = threading.Timer(45, expire)
        deadline.daemon = True
        deadline.start()
        hints = dictate_hints(first, dictate_words())
        if expired.is_set():
            return print(''.join(dictate_fallback(chunk) + separator for chunk, separator in chunks).rstrip(), flush=True)
        corrections = dictate_spellings(first, hints) + ('Text before the cursor: ' + json.dumps(before, ensure_ascii=False) + '\n' if before else '')
        try:
            cleaned = [(dictate_warmed(p, first, corrections, hints), first_separator)]
        except Exception:
            cleaned = [(dictate_fallback(first), first_separator)]
        if len(chunks) == 1:   # Rabik inserts at end of output: close it before stopping Claude
            print(cleaned[0][0], flush=True)
            try:
                os.close(sys.stdout.fileno())
            except OSError:   # not a real file (tests)
                pass
            return
    finally:
        if deadline:
            deadline.cancel()
        clients.stop_claude(p)
    cleaned.extend((dictate_cleanup(chunk), separator) for chunk, separator in chunks[1:])
    print(''.join(value + separator for value, separator in cleaned).rstrip(), flush=True)
