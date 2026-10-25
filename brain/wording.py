"""Plain-text matching for spoken requests: normalizing, stop and filler words, "this/that", failure replies."""
import re

__all__ = ['dashes', 'plain', 'STOP', 'FILLER', 'gist', '_words', 'DEICTIC', 'MORE', 'FAILED', 'failed_action_reply', 'NUMS',
           'norm']


def _words(value):
    words = set(re.findall(r'[a-z0-9]+', str(value).lower()))
    return words | {w[:-1] for w in words if len(w) > 3 and w.endswith('s')} | {w[:-2] for w in words if len(w) > 4 and w.endswith('es')}


NUMS = dict(zip('zero one two three four five six seven eight nine ten'.split(), map(str, range(11))))


def norm(name):
    """Spoken playlist name -> comparable key: "One M" and "1m" both give "1m"."""
    return re.sub(r'[^a-z0-9]', '', ''.join(NUMS.get(w, w) for w in name.lower().split()))


def dashes(text):
    return re.sub(r'[\u2010-\u2015\u2212]', '-', text)   # macOS writes "Wi‑Fi" with a non-breaking hyphen


def plain(text):
    """Spoken request -> its core words: "Hey Rabik, can you open Spotify please?" -> "open spotify"."""
    t = re.sub(r'[,;!?]|:(?!//)|(?<!\w)\.|\.(?!\w)', '', text.lower().strip(' .!?')).strip()   # keep domain dots; normalize punctuation before spoken prefixes
    return re.sub(r'^(?:(?:hey|ok|okay|um+|uh+|hmm+|rabik|please|also|and|now|then|(?:can|could|would|will) (?:you|u)) )+|(?:\s+(?:please|for me))+$', '', t)


DEICTIC = re.compile(r'\b(this|that|these|those|it|here|there|them|him|her)\b')   # "close this" depends on the moment: never learned


MORE = re.compile(r'\b(and|then|after that|also)\b', re.I)   # a second step after an instant command's free text


FAILED = re.compile(r"\b(can't|cannot|couldn't|could not|unable|not able|failed|not done|not completed|didn't work)\b", re.I)   # the reply admits it did not work


def failed_action_reply(reply, did_action):
    """Failure wording counts only after an action; ordinary explanations use the same words."""
    return bool(did_action and FAILED.search(reply))


FILLER = set('um uh umm hmm like so bro yeah just actually okay ok hey wait new again also now then quick quickly real'.split())


def gist(text):
    """The words that matter, in order: "um, can you make a new Zoom meeting?" == "start a zoom meeting"."""
    return [{'create': 'make', 'start': 'make'}.get(w, w) for w in re.findall(r"[a-z0-9'.-]+", plain(text)) if w not in STOP | FILLER]


STOP = set('a an the to of in on and or for my me i you it is be do can could would please with at this that what how'.split())
