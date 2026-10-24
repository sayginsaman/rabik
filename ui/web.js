// Runs inside the user's browser tab (atticus.py --web, through AppleScript): read the page, click or fill by number.
// One expression, called as (src)(cmd, n, text). Numbers refer to the controls saved by the last read.
(function (cmd, n, text) {
  const clean = s => (s || '').trim().replace(/\s+/g, ' ');
  const secrets = window.__atticusSecrets ||= new WeakSet();
  const secret = e => {
    const token = clean(e.autocomplete).toLowerCase().split(' ');
    if (e.type === 'password' || token.includes('current-password') || token.includes('one-time-code')) secrets.add(e);
    return secrets.has(e);   // stays secret after a reveal control changes password to text
  };
  const value = e => String(e.value ?? e.innerText ?? '');
  const name = e => clean(e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => e.ownerDocument.getElementById(id)?.innerText || '').join(' ') || [...(e.labels || [])].map(l => l.innerText).join(' ') || e.innerText || e.placeholder || e.title || e.name || (secret(e) ? 'password' : e.value || '')).slice(0, 160);
  const identity = e => JSON.stringify([e.tagName, e.type, e.id, e.name, isBox(e) ? clean(e.getAttribute('aria-label') || [...(e.labels || [])].map(l => l.innerText).join(' ') || e.placeholder || e.title) : name(e), e.getAttribute('href'), e.getAttribute('role'), e.form?.action, e.ownerDocument.location.href, location.href]);
  const isBox = e => e.isContentEditable || e.tagName === 'TEXTAREA' || (e.tagName === 'INPUT' && !/^(button|submit|reset|checkbox|radio|image|file)$/.test(e.type));
  const pageState = () => {
    const busy = [...document.querySelectorAll('[aria-busy="true"]')].some(e => { const r=e.getBoundingClientRect();return r.width&&r.height&&getComputedStyle(e).visibility!=='hidden'; });
    let hash=0;for(const c of (document.body?.innerText||'').slice(0,3000))hash=(hash*31+c.charCodeAt(0))|0;
    return {ready:document.readyState!=='loading'&&!!document.body&&!busy,signature:location.href+'|'+hash,title:document.title};
  };
  if (cmd === 'ready') {
    return JSON.stringify(pageState());
  }
  if (cmd === 'read') {
    const offset = Number(n || 0);
    if (!Number.isSafeInteger(offset) || offset < 0) return 'Use a nonnegative read offset.';
    if (offset === 0) {
      const seen = [], bodies = [], frames = [];
      const scan = doc => {
        bodies.push(`${doc.location.href}\n${doc.title}\n${(doc.body?.innerText || '').replace(/\n\s*\n+/g, '\n')}`);
        for (const e of doc.querySelectorAll('a[href],button,input:not([type=hidden]),textarea,select,[contenteditable=true],[contenteditable=""],[role=button],[role=link],[role=textbox],[role=tab],[role=menuitem],[role=checkbox],[role=radio],[role=option],[role=combobox]')) {
          const r = e.getBoundingClientRect(), s = doc.defaultView.getComputedStyle(e);
          if (!r.width || !r.height || s.visibility === 'hidden') continue;
          const label = name(e), box = isBox(e);
          if (!label && !box && e.tagName !== 'SELECT') continue;
          const kind = box ? 'box' : e.tagName === 'SELECT' ? 'menu' : /^(checkbox|radio)$/.test(e.type) ? e.type : e.getAttribute('role') === 'checkbox' ? 'checkbox' : e.tagName === 'A' ? 'link' : 'button';
          seen.push({ e, kind, label, box });
        }
        for (const frame of doc.querySelectorAll('iframe,frame')) {
          try { if (frame.contentDocument?.body) { scan(frame.contentDocument); continue; } } catch (_) {}
          const r = frame.getBoundingClientRect(), view = doc.defaultView;   // another site's frame: the page script cannot open it
          if (r.width < 20 || r.height < 20 || view.getComputedStyle(frame).visibility === 'hidden') continue;   // tracking pixels hold no fields
          let host = ''; try { host = new URL(frame.src).host; } catch (_) {}
          frames.push(`Frame from ${host || 'another site'} (${r.top >= view.innerHeight ? 'below the view' : r.bottom <= 0 ? 'above the view' : 'on screen'}): its fields and text are NOT in this read. Scroll to it, then --hands see/type.`);
        }
      };
      scan(document);
      const ordered = [...seen.filter(c => c.kind !== 'link'), ...seen.filter(c => c.kind === 'link')];
      const controls = ordered.slice(0, 150), omitted = ordered.length - controls.length;
      window.__atticusControls = controls.map(({e}) => ({e, identity:identity(e)}));
      const out = controls.map(({ e, kind, label, box }, i) => {
        const group = clean(e.closest('fieldset')?.querySelector('legend')?.innerText);
        const current = secret(e) ? '' : box || e.tagName === 'SELECT' ? ` = ${JSON.stringify(value(e).slice(0, 60))}` : /^(checkbox|radio)$/.test(e.type) ? ` checked=${e.checked}` : '';
        return `${i + 1} ${kind}: ${label}${group ? ` (question: ${group})` : ''}${current}${e.disabled ? ' disabled=true' : ''}${e.readOnly ? ' readonly=true' : ''}`;
      });
      if (omitted) out.push(`${omitted} more controls omitted`);
      window.__atticusRead = { url: location.href, text: 'Controls:\n' + [...frames, ...out].join('\n') + '\n\nPage text:\n' + bodies.join('\n\n') };
    }
    const snapshot = window.__atticusRead;
    if (!snapshot || snapshot.url !== location.href) return 'The page changed. Read again at offset 0.';
    const end = Math.min(offset + 8000, snapshot.text.length);
    return snapshot.text.slice(offset, end) + `\n[Read ${offset}-${end} of ${snapshot.text.length} chars${end < snapshot.text.length ? `; ${snapshot.text.length-end} more chars; --window --offset ${end}` : '; end'}]`;
  }
  if (cmd === 'type-after') {
    const anchor = String(n || '');
    if (!anchor) return 'Use exact nonempty anchor text.';
    const docs = [], scanDocs = doc => {
      docs.push(doc);
      for (const frame of doc.querySelectorAll('iframe,frame')) try { if (frame.contentDocument?.body) scanDocs(frame.contentDocument); } catch (_) {}
    };
    scanDocs(document);
    const hits = [];
    for (const doc of docs) {
      const walker = doc.createTreeWalker(doc.body,NodeFilter.SHOW_TEXT), nodes=[]; let joined='';
      for (let node; node=walker.nextNode();) if (!node.parentElement?.closest('script,style,noscript')) { nodes.push({node,start:joined.length}); joined+=node.data; }
      for (let at=joined.indexOf(anchor); at>=0; at=joined.indexOf(anchor,at+anchor.length)) {
        const end=at+anchor.length, part=nodes.findLast(p=>p.start<end);
        if (part) hits.push({doc,node:part.node,at:end-part.start});
      }
    }
    if (hits.length !== 1) return hits.length ? `More than one passage matches "${anchor}". Use a longer exact anchor.` : `No passage matches "${anchor}". Read again.`;
    const hit = hits[0], editable = hit.node.parentElement?.closest('[contenteditable=true],[contenteditable=""],textarea,input:not([type]),input[type=text],input[type=search],input[type=email],input[type=url],input[type=tel],input[type=number]');
    const anchorLives = () => docs.some(doc => (doc.body?.innerText || '').includes(anchor));
    const current = target => target.isContentEditable ? target.textContent : value(target);
    const rendered = target => target.isContentEditable ? target.innerText : current(target);
    if (editable?.isContentEditable) {
      const before = editable.textContent, beforeRendered = editable.innerText, range = hit.doc.createRange(), selection = hit.doc.getSelection();
      const prefix = hit.doc.createRange(); prefix.selectNodeContents(editable); prefix.setEnd(hit.node,hit.at);
      const location = prefix.toString().length;
      editable.focus();
      range.setStart(hit.node, hit.at); range.collapse(true);
      selection.removeAllRanges(); selection.addRange(range);
      hit.doc.execCommand('insertText', false, text);
      editable.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));
      const expected = before.slice(0,location) + text + before.slice(location);
      const renderedLocation = beforeRendered.indexOf(anchor) + anchor.length, expectedRendered = beforeRendered.slice(0,renderedLocation) + text + beforeRendered.slice(renderedLocation);
      if (current(editable) === expected && rendered(editable) === expectedRendered && anchorLives()) return `Typed after "${anchor}" and verified the original text.`;
      if (current(editable) !== before || rendered(editable) !== beforeRendered) {
        hit.doc.execCommand('undo');
        if (current(editable) !== before || rendered(editable) !== beforeRendered) return 'The edit did not verify. Stop and read the document before continuing.';
      }
      const inserted = hit.doc.createTextNode(text);
      range.insertNode(inserted);
      editable.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));
      if (current(editable) === expected && rendered(editable) === expectedRendered && anchorLives()) return `Typed after "${anchor}" and verified the original text.`;
      inserted.remove();
      return current(editable) === before && rendered(editable) === beforeRendered ? 'The edit did not verify and was undone.' : 'The edit did not verify. Stop and read the document before continuing.';
    }
    const selector = 'input:not([type]),input[type=text],input[type=search],input[type=email],input[type=url],input[type=tel],input[type=number],textarea,[contenteditable=true],[contenteditable=""]';
    const after = e => hit.node.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING;
    const row = hit.node.parentElement?.closest('tr');
    const candidates = [...(row?.querySelectorAll(selector) || []), ...hit.doc.querySelectorAll(selector)]
      .filter((e,i,a) => a.indexOf(e) === i && after(e) && !e.disabled && !e.readOnly && value(e) === '');
    const target = candidates[0];
    if (!target) return `No empty editable area follows "${anchor}".`;
    const before = value(target);
    target.focus();
    if (target.isContentEditable) hit.doc.execCommand('insertText',false,text);
    else Object.getOwnPropertyDescriptor(Object.getPrototypeOf(target),'value').set.call(target,text);
    target.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));
    target.dispatchEvent(new Event('change',{bubbles:true}));
    if (current(target) === text && anchorLives()) return `Typed after "${anchor}" and verified the original text.`;
    if (current(target) !== before) {
      target.ownerDocument.execCommand('undo');
      if (current(target) !== before) return 'The edit did not verify. Stop and read the document before continuing.';
    }
    const inserted = target.ownerDocument.createTextNode(text);
    if (target.isContentEditable) target.append(inserted);
    target.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));
    if (current(target) === text && anchorLives()) return `Typed after "${anchor}" and verified the original text.`;
    inserted.remove();
    return current(target) === before ? 'The edit did not verify and was undone.' : 'The edit did not verify. Stop and read the document before continuing.';
  }
  const control = /^\d+$/.test(n) && window.__atticusControls?.[Number(n) - 1], e = control?.e;
  if (!e || !e.isConnected || e.ownerDocument.defaultView?.document !== e.ownerDocument) return `No control ${n}. Read the page again.`;
  if (identity(e) !== control.identity) return 'The control changed since the read. Read the page again.';
  if (cmd === 'state') return JSON.stringify({label:name(e),value:secret(e) ? '[SECRET]' : e.value ?? e.innerText,checked:e.checked,disabled:e.disabled,readonly:e.readOnly,page:pageState()});
  // name: everything that says what a click does (full label, link, form that posts), for the Allow check; plus the tab it is in
  if (cmd === 'name') return JSON.stringify({ what: clean([e.getAttribute('aria-label'), e.innerText, secret(e) ? '' : e.value, e.title, e.href, e.form && e.type === 'submit' ? 'submits a form ' + e.form.action : ''].filter(Boolean).join(' ')), short: name(e), url: location.href, submit: !!e.form && e.type === 'submit' });
  if (text && cmd === 'click' && location.href !== text) return 'The tab changed since the check. Read the page again.';
  if (e.disabled || cmd === 'fill' && e.readOnly) return 'This control is disabled or read-only. Read its preconditions before acting.';
  e.scrollIntoView({ block: 'center' });   // the mini screen shows what is being clicked or filled
  if (cmd === 'click') {   // the full press, for sites that listen to mousedown/up rather than click
    for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup']) e.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: e.ownerDocument.defaultView }));
    const link = e.closest('a[href]'), target = link?.getAttribute('target');
    if (link) link.setAttribute('target', '_self');   // navigation stays in the pinned tab, including links that request a new window
    try { e.click(); } finally { if (link) { if (target === null) link.removeAttribute('target'); else link.setAttribute('target', target); } }
    return `Clicked ${n}: ${name(e)}`;
  }
  if (cmd === 'fill') {
    if (e.tagName === 'SELECT') {
      const o = [...e.options].find(o => clean(o.text).toLowerCase().includes(text.toLowerCase()));
      if (!o) return `No option "${text}" in ${n}.`;
      e.value = o.value;
    } else if (e.isContentEditable) {
      if (value(e)) return 'This rich editor already has text. Use type-after so the original text is preserved.';
      e.focus(); e.ownerDocument.execCommand('selectAll'); e.ownerDocument.execCommand('insertText', false, text);
    } else if (isBox(e)) {   // the native setter, so React and other frameworks see the change
      Object.getOwnPropertyDescriptor(Object.getPrototypeOf(e), 'value').set.call(e, text);
    } else return `${n} is not a box.`;
    e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true }));
    return `Filled ${n}: ${name(e)}` + (secret(e) ? '' : ` = "${(e.value ?? e.innerText).slice(0, 600)}"`);
  }
  return 'Use read, click, fill or type-after.';
})
