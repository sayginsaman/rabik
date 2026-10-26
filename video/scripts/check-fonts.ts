// Step 0, fonts: can Figtree and JetBrains Mono load from Google Fonts? Writes src/fonts.status.json (fonts.ts loads them only
// when they can) and out/log/fonts.md for the build log. npm run fonts
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { VIDEO } from './lib/render.ts';

const scene = JSON.parse(readFileSync(join(VIDEO, 'scene.v1.json'), 'utf8'));
const families: Record<string, { css: string; fallbacks: string[] }> = {
  Figtree: { css: 'https://fonts.googleapis.com/css2?family=Figtree:wght@500;600;800&display=block', fallbacks: scene.brand.fonts.display.slice(1) },
  'JetBrains Mono': { css: 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500&display=block', fallbacks: scene.brand.fonts.mono.slice(1) },
};
const result: Record<string, string> = {};
for (const [name, f] of Object.entries(families)) {
  try {
    const css = await (await fetch(f.css, { signal: AbortSignal.timeout(8000) })).text();
    const woff = css.match(/url\((https:[^)]+)\)/)?.[1];   // woff2 for browsers, ttf for this request: either proves it loads
    if (!woff) throw new Error('no font file in the stylesheet');
    const res = await fetch(woff, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) throw new Error(`font file: HTTP ${res.status}`);
    result[name] = 'ok';
  } catch (e) { result[name] = `failed (${(e as Error).message})`; }
}
const google = Object.values(result).every(v => v === 'ok');
writeFileSync(join(VIDEO, 'src/fonts.status.json'), JSON.stringify({ google, checked: new Date().toISOString(), families: result }, null, 1) + '\n');
mkdirSync(join(VIDEO, 'out/log'), { recursive: true });
writeFileSync(join(VIDEO, 'out/log/fonts.md'), [
  '## Fonts',
  ...Object.entries(result).map(([n, r]) => r === 'ok' ? `- ${n}: loads from Google Fonts through @remotion/google-fonts.` : `- **Fallback:** ${n} ${r}; the video uses ${families[n].fallbacks.join(', then ')}.`),
  '- ⌃ and ⌥ are not in either font\'s Latin subset: those two glyphs come from the system font (SF) in the caption, keycaps and closing line.',
  '- Text inside the screenshots is Rabik\'s own (SF Pro, drawn by WebKit at capture time); typed text over the box uses the same -apple-system stack.',
].join('\n') + '\n');
console.log(`fonts: ${JSON.stringify(result)}`);
