// out/build-log.md: fonts, captures and skipped scenes, upscales, the timing plan, the choices made where the brief and the app
// differ, and every QA report so far. qa.ts runs this after each check; npx tsx scripts/build-log.ts on its own works too.
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { CAPTURE } from '../src/data.ts';
import { plan } from '../src/timing.ts';
import { VIDEO } from './lib/render.ts';

const read = (f: string) => (existsSync(f) ? readFileSync(f, 'utf8').trim() : '');
const p = plan({});
const captures = Object.entries(CAPTURE.scenes).map(([id, c]) => `| ${id} | ${c.status} | ${c.status === 'captured' ? (c as { page?: string }).page ?? 'live capture' : c.reason ?? 'brand files only'} |`);
const upscales = read(join(VIDEO, 'out/normalize-log.md')).split('\n').filter(l => l.includes('upscaled'));
const qa = existsSync(join(VIDEO, 'out/log')) ? readdirSync(join(VIDEO, 'out/log')).filter(f => f.startsWith('qa-')).sort().map(f => read(join(VIDEO, 'out/log', f))) : [];

writeFileSync(join(VIDEO, 'out/build-log.md'), `# Build log

Generated ${new Date().toISOString().slice(0, 16).replace('T', ' ')} by scripts/build-log.ts.

${read(join(VIDEO, 'out/log/fonts.md')) || '## Fonts\n- Not checked yet: npm run fonts'}

## Captures

| Scene | Status | Source |
|---|---|---|
${captures.join('\n')}

- Method A (preferred) used WebKit, not Chromium: Rabik draws these pages in WKWebView, so scripts/capture.swift renders them in an offscreen WKWebView (the engine the app uses) at 2.5× with demo data from fixtures/.
- The agent chip's mini screen is native (a live picture of the agent's Chrome window); fixtures/mini_shop.html, a plain unbranded results page, stands in for it.
- The agent shelf and meeting panel sit 76 and 84 pt in from the right edge (the app's default is 12 pt; both panels can be dragged) so the full-bleed crop keeps them inside the safe area.
${upscales.length ? upscales.join('\n') : '- Upscales: none. Every panel is captured at 2.5 px per point, the size the desktop is drawn at.'}

## Skipped scenes

${p.skipped.length ? p.skipped.map(s => `- **${s.id}**: ${s.reason} See CAPTURE.md.`).join('\n') : '- None.'}

## Timing (45 s default)

| Scene | Start (s) | Length (s) | Stretch |
|---|---|---|---|
${p.scenes.map(s => `| ${s.def.id} | ${(s.from / 30).toFixed(2)} | ${(s.frames / 30).toFixed(2)} | ×${s.k.toFixed(2)} |`).join('\n')}

${p.warnings.map(w => `- Warning: ${w}`).join('\n') || '- No timing warnings.'}

## Where the video follows the app rather than the brief

- **Confirm card:** the app's card for a calendar move says "Move this event?" with **Don't Allow / Allow**, and times as "4:00 PM" (brain/calendar.py). The video shows it as the app draws it; the pointer presses **Allow**, not "Confirm".
- **Evening recap:** the recap card has no source chips; its to-dos carry their source as a line ("Northstar weekly · due Oct 27"). The spotlight lands on that to-do and it gets ticked (the "expand" beat). Source chips are shown in scene 2, where answers have them. The box can only scroll the recap until the to-dos sit a third of the way down, not 0.8 of a screen.
- **Typing in the box:** a voice ask arrives as live words in the ask bubble; the video types them in the bubble's own font, with the bubble's own caret (white, ui.html .q.live::after), then hands over to the captured box. The brief's Ink caret would not show on the dark box.
- **Summary sections:** revealed 16 frames each, 2 frames apart, as the note in scene.v1.json says.
- **Hero wordmark:** set in Figtree 800 as scene.v1.json asks; the brand kit prefers its PNG wordmark (used in the closing lockup).

${qa.length ? qa.join('\n\n') : '## QA\n\nNo renders checked yet.'}
`);
console.log('out/build-log.md written');
