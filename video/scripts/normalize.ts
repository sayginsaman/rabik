// Raw captures (assets/screens/raw, from scripts/capture.swift) → the screens the video shows and assets/screens/capture-map.json.
// Each scene is a 1152×720 pt demo desktop (2.5 px per pt, 2880×1800) with Rabik's panels where the app puts them; regions are
// desktop points, so spotlights, pointers and typing land on the real elements. Run after npm run capture: npm run normalize
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const VIDEO = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO = resolve(VIDEO, '..');
const SCREENS = join(VIDEO, 'assets/screens'), RAW = join(SCREENS, 'raw');
const { color, radius } = await import('../src/theme.ts');
const scene = JSON.parse(readFileSync(join(VIDEO, 'scene.v1.json'), 'utf8'));

const DESK = { w: 1152, h: 720, scale: 2.5 };   // a 16:10 display; the box's 440 pt then reads at video size
type Rect = [number, number, number, number];
type Raw = { size: [number, number]; scale: number; panel: string; regions: Record<string, Rect | Rect[]>; styles: Record<string, Record<string, string>> };
type PanelSpec = { shot: string; x: number | 'center'; y: number; right?: number; viewport?: { h: number; fixedTop?: string; fixedBottom?: string } };
type SceneSpec = { page: string; panels: PanelSpec[]; states?: Record<string, string>; mini?: string; focus: string };

// Where the app draws each panel: the box at the top center; the agent shelf and meeting panel on the right, dragged in from the
// edge (both are movable in the app) so the full-bleed crop keeps them inside the safe area
const LAYOUT: Record<string, SceneSpec> = {
  ask: { page: 'ui/ui.html', panels: [{ shot: 'ask', x: 'center', y: 52 }], states: { full: 'ask_full' }, focus: 'box' },
  summary: { page: 'ui/ui.html', panels: [{ shot: 'summary', x: 'center', y: 52 }], focus: 'summaryCard' },
  agent: { page: 'ui/agents.html', panels: [{ shot: 'agent', x: 0, right: 76, y: 24 }], states: { done: 'agent_done' }, mini: 'mini_shop', focus: 'chip' },
  meeting: { page: 'ui/meeting.html', panels: [{ shot: 'meeting_transcript', x: 0, right: 84, y: 52, viewport: { h: 520, fixedTop: 'lines', fixedBottom: 'footer' } }],
             states: { recap: 'meeting_recap', ticked: 'meeting_recap_ticked' }, focus: 'transcript' },
  safe: { page: 'ui/ui.html', panels: [{ shot: 'confirm', x: 'center', y: 52 }], focus: 'confirmCard' },
  recap: { page: 'ui/ui.html', panels: [{ shot: 'recap', x: 'center', y: 52, viewport: { h: 520, fixedTop: 'card' } }], states: { ticked: 'recap_ticked' }, focus: 'todo' },
};
// Screens that exist only natively or in another app's window: CAPTURE.md says how to make them
const LIVE: Record<string, { reason: string; needs: string[] }> = {
  guide: { reason: 'System Settings and Rabik\'s ring and step overlays are native windows (Sources/Rabik/Drawing); no HTML page draws them.',
           needs: ['raw/guide_before.png', 'raw/guide.png', 'raw/guide.json'] },
  dictate: { reason: 'The text field belongs to Mail (another app). Rabik\'s dictation pill is HTML (captured as dictate_pill), but the field it types into is not.',
             needs: ['raw/dictate_field.png', 'raw/dictate.json'] },
};

const raw = (id: string): Raw => JSON.parse(readFileSync(join(RAW, `${id}.json`), 'utf8'));
const r2 = (n: number) => Math.round(n * 100) / 100;
const shift = (r: Rect, dx: number, dy: number): Rect => [r2(r[0] + dx), r2(r[1] + dy), r2(r[2]), r2(r[3])];
const isList = (v: Rect | Rect[]): v is Rect[] => Array.isArray(v[0]);

// The demo desktop: Cloud with a Haze glow and two soft, blurred windows, so overlays sit on something without anyone's wallpaper
async function wallpaper(file: string) {
  const W = DESK.w * DESK.scale, H = DESK.h * DESK.scale;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}">
    <defs><radialGradient id="g" cx="78%" cy="88%" r="75%"><stop offset="0" stop-color="${color.haze}" stop-opacity=".95"/><stop offset="1" stop-color="${color.haze}" stop-opacity="0"/></radialGradient>
    <linearGradient id="l" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${color.bg}"/><stop offset="1" stop-color="${color.surface}"/></linearGradient>
    <filter id="b" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="22"/></filter>
    <filter id="s" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="60"/></filter></defs>
    <rect width="100%" height="100%" fill="url(#l)"/><rect width="100%" height="100%" fill="url(#g)"/>
    <g filter="url(#s)" opacity=".35"><rect x="${W * .09}" y="${H * .2}" width="${W * .5}" height="${H * .62}" rx="60" fill="${color.ink}" opacity=".25"/></g>
    <g filter="url(#b)">
      <rect x="${W * .08}" y="${H * .16}" width="${W * .5}" height="${H * .64}" rx="${radius.lg * DESK.scale}" fill="${color.bg}" stroke="${color.border}" stroke-width="4"/>
      <rect x="${W * .08}" y="${H * .16}" width="${W * .5}" height="${H * .07}" rx="${radius.lg * DESK.scale}" fill="${color.surface}"/>
      ${[0, 1, 2, 3, 4, 5].map(i => `<rect x="${W * .11}" y="${H * (.29 + i * .07)}" width="${W * (i % 3 === 2 ? .26 : .4)}" height="${H * .025}" rx="20" fill="${color.border}"/>`).join('')}
      <rect x="${W * .5}" y="${H * .42}" width="${W * .38}" height="${H * .44}" rx="${radius.lg * DESK.scale}" fill="${color.surface}" stroke="${color.border}" stroke-width="4"/>
      <rect x="${W * .53}" y="${H * .5}" width="${W * .15}" height="${H * .2}" rx="30" fill="${color.haze}" opacity=".8"/>
      <rect x="${W * .7}" y="${H * .5}" width="${W * .15}" height="${H * .2}" rx="30" fill="${color.border}"/>
    </g></svg>`;
  await sharp(Buffer.from(svg)).png().toFile(file);
}

const log: string[] = [];
const map: Record<string, unknown> = {};
const placed: Record<string, { panels: unknown[]; regions: Record<string, Rect | Rect[]>; styles: Record<string, unknown>; states: Record<string, unknown>; mini?: unknown }> = {};

for (const [id, spec] of Object.entries(LAYOUT)) {
  const panels = spec.panels.map(p => {
    const r = raw(p.shot), [w, h] = r.size;
    const x = p.x === 'center' ? (DESK.w - w) / 2 : p.right !== undefined ? DESK.w - p.right - w : p.x;
    const reg = (name?: string) => (name ? (r.regions[name] as Rect) : undefined);
    const vp = p.viewport && {
      h: p.viewport.h,
      fixedTop: p.viewport.fixedTop ? r2(reg(p.viewport.fixedTop)![1]) : 0,
      fixedBottom: p.viewport.fixedBottom ? r2(h - reg(p.viewport.fixedBottom)![1]) : 0,
    };
    // Normalize rules: panels are 2.5× their on-screen size, never upscaled (WebKit draws them at that scale)
    if (r.scale < DESK.scale) log.push(`- ${p.shot}: upscaled ${(DESK.scale / r.scale).toFixed(2)}×`);
    return { id: p.shot, src: `screens/raw/${p.shot}.png`, x: r2(x), y: p.y, w: r2(w), h: r2(h), viewport: vp, radius: r.panel === 'none' ? 0 : r.panel === 'window' ? 12 : 18 };
  });
  const main = panels[0], first = raw(spec.panels[0].shot);
  const toDesk = (rs: Raw['regions']) => Object.fromEntries(Object.entries(rs).map(([k, v]) => [k, isList(v) ? v.map(q => shift(q, main.x, main.y)) : shift(v, main.x, main.y)]));
  const regions = toDesk(first.regions);
  if (id === 'recap') regions.todo = (regions.todos as Rect[])[0];
  const states = Object.fromEntries(Object.entries(spec.states ?? {}).map(([k, shot]) => {
    const r = raw(shot);
    return [k, { id: shot, src: `screens/raw/${shot}.png`, x: main.x, y: main.y, w: r2(r.size[0]), h: r2(r.size[1]), regions: toDesk(r.regions), styles: r.styles }];
  }));
  if (!regions[spec.focus]) throw new Error(`${id}: focus region "${spec.focus}" was not measured`);
  const mini = spec.mini && { src: `screens/raw/${spec.mini}.png`, size: raw(spec.mini).size, note: 'Stand-in for the native mini screen: a plain, unbranded results page' };
  placed[id] = { panels, regions, styles: first.styles, states, mini };
  map[id] = { status: 'captured', method: 'A: the page in an offscreen WKWebView (the app\'s own engine), demo data from video/fixtures',
              page: spec.page, fixtures: [spec.panels[0].shot, ...Object.values(spec.states ?? {})].map(s => `fixtures/${s}.js`),
              screen: `screens/${id}.png`, focus: spec.focus, ...placed[id] };
}
for (const [id, live] of Object.entries(LIVE)) {
  const have = live.needs.every(f => existsSync(join(SCREENS, f)));
  map[id] = have ? { status: 'captured', method: 'B: live capture (CAPTURE.md)', ...JSON.parse(readFileSync(join(SCREENS, live.needs.find(f => f.endsWith('.json'))!), 'utf8')) }
                 : { status: 'needs-live-capture', method: 'B', reason: live.reason, needs: live.needs.map(f => `assets/screens/${f}`), see: 'CAPTURE.md' };
  if (!have) log.push(`- ${id}: skipped, needs live capture (${live.reason})`);
}

// The flat screen per scene (first state, scrolled to the top): storyboard stills and anyone who wants the picture alone
const desktop = join(SCREENS, 'desktop.png');
await wallpaper(desktop);
for (const [id, p] of Object.entries(placed)) {
  const layers: sharp.OverlayOptions[] = [];
  for (const panel of p.panels as { src: string; x: number; y: number; w: number; h: number; viewport?: { h: number } }[]) {
    let img = sharp(join(VIDEO, 'assets', panel.src));
    if (panel.viewport) img = img.extract({ left: 0, top: 0, width: Math.round(panel.w * DESK.scale), height: Math.round(panel.viewport.h * DESK.scale) });
    layers.push({ input: await img.png().toBuffer(), left: Math.round(panel.x * DESK.scale), top: Math.round(panel.y * DESK.scale) });
  }
  if (p.mini) {
    const m = p.regions.mini as Rect, [w, h] = [Math.round(m[2] * DESK.scale), Math.round(m[3] * DESK.scale)];
    const pic = await sharp(join(VIDEO, 'assets', (p.mini as { src: string }).src)).resize(w, h, { fit: 'cover', position: 'top' })
      .composite([{ input: Buffer.from(`<svg width="${w}" height="${h}"><rect width="${w}" height="${h}" rx="${10 * DESK.scale}" fill="${color.ink}"/></svg>`), blend: 'dest-in' }]).png().toBuffer();
    layers.push({ input: pic, left: Math.round(m[0] * DESK.scale), top: Math.round(m[1] * DESK.scale) });
  }
  await sharp(desktop).composite(layers).png().toFile(join(SCREENS, `${id}.png`));
}

// Step 0's map: every file in ui/ and what the video takes from it
const roles: Record<string, string> = {
  'ui.html': 'The box: the ask (ask, ask_full), the answer with source chips (summary), the confirm card (confirm), the evening recap (recap, recap_ticked), the dictation pill (dictate_pill)',
  'agents.html': 'The agent shelf: the corner chip with live steps (agent) and done (agent_done); its mini screen is native, a stand-in page fills it',
  'meeting.html': 'Meeting Copilot: the live transcript (meeting_transcript) and the recap with action items (meeting_recap, meeting_recap_ticked)',
  'settings.html': 'Settings window: not in the shot list. Night Shift lives in System Settings, not here',
  'onboarding.html': 'Setup: not in the shot list', 'orbs.js': 'The orb animation, inlined into the pages at /*ORBS*/', 'web.js': 'Shared page helpers',
  'AppIcon.icns': 'The app icon (the video uses the brand kit\'s PNG)', 'logo.png': 'Old logo, unused', 'brand': 'The brand kit (copy of Rabik_Brand_Kit)', 'Rabik_Brand_Kit': 'The brand kit as delivered',
};
const ui = readdirSync(join(REPO, 'ui')).filter(f => !f.startsWith('.')).map(f => ({ file: `ui/${f}`, use: roles[f] ?? 'Unused' }));
writeFileSync(join(SCREENS, 'capture-map.json'), JSON.stringify({
  generatedBy: 'video/scripts/normalize.ts', desktop: { size: [DESK.w, DESK.h], scale: DESK.scale, wallpaper: 'screens/desktop.png', units: 'points; multiply by scale for pixels' },
  ui, scenes: Object.fromEntries(scene.scenes.map((s: { id: string }) => [s.id, map[s.id] ?? { status: 'brand-only' }])),
}, null, 1));
writeFileSync(join(VIDEO, 'out/normalize-log.md'), log.join('\n') + '\n');
console.log(`capture-map.json: ${Object.keys(placed).length} captured scenes, ${Object.keys(LIVE).filter(k => (map[k] as { status: string }).status !== 'captured').length} need live capture\n${log.join('\n')}`);
