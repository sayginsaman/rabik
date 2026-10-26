// Section 11's checks on a rendered MP4; exits 1 when any fails. npx tsx scripts/qa.ts out/<name>.mp4 ['<props json>']
// Contrast and brand are measured on frames pulled from the file itself; safe area, visibility and speed come from the same
// geometry the renderer draws with (src/scenes/geometry.ts), every frame.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import sharp from 'sharp';
import { CAPTURE, SCENE, type Rect } from '../src/data.ts';
import { DEVICE, SAFE, toFrame, viewportOf } from '../src/layout.ts';
import type { SceneTime } from '../src/motion/anim.ts';
import { geometry } from '../src/scenes/geometry.ts';
import { color, brandImages } from '../src/theme.ts';
import { defaultProps, plan, type ShowcaseProps } from '../src/timing.ts';
import { VIDEO } from './lib/render.ts';

const [file, rawProps] = process.argv.slice(2);
if (!file || !existsSync(file)) { console.error('usage: qa.ts <video.mp4> [props json]'); process.exit(2); }
const props: ShowcaseProps = { ...defaultProps, ...JSON.parse(rawProps || '{}') };
const p = plan(props), name = basename(file, '.mp4');
const rows: { check: string; ok: boolean; level?: 'warn'; detail: string }[] = [];
const add = (check: string, ok: boolean, detail: string, level?: 'warn') => rows.push({ check, ok, detail, level });

// ── The file: frames, fps, size, audio
const probe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-count_frames', '-show_entries', 'stream=codec_type,codec_name,nb_read_frames,r_frame_rate,width,height,pix_fmt', '-of', 'json', file], { encoding: 'utf8' }));
const video = probe.streams.find((s: { codec_type: string }) => s.codec_type === 'video'), audio = probe.streams.filter((s: { codec_type: string }) => s.codec_type === 'audio');
const W = video.width, H = video.height, S = W / SCENE.width, frames = Number(video.nb_read_frames);
add('Duration', frames === props.targetSeconds * SCENE.fps && frames === p.total, `${frames} frames; target ${props.targetSeconds} s × ${SCENE.fps} = ${props.targetSeconds * SCENE.fps}`);
add('Frame rate', video.r_frame_rate === `${SCENE.fps}/1`, video.r_frame_rate);
add('No audio', audio.length === 0, audio.length ? `${audio.length} audio stream(s)` : 'no audio stream');
add('Codec', video.codec_name === 'h264' && video.pix_fmt === 'yuv420p', `${video.codec_name}, ${video.pix_fmt}, ${W}×${H}`);

// ── Frames pulled from the file
const TMP = join(VIDEO, 'out/qa', name);
rmSync(TMP, { recursive: true, force: true }); mkdirSync(TMP, { recursive: true });
const wanted = new Map<number, string>();
const frameFile = (n: number) => { if (!wanted.has(n)) wanted.set(n, join(TMP, `f${String(n).padStart(4, '0')}.png`)); return wanted.get(n)!; };
type Px = { data: Buffer; w: number; h: number };
const pending: { n: number; run: (px: Px) => Promise<void> | void }[] = [];
const at = (n: number, run: (px: Px) => Promise<void> | void) => { frameFile(n); pending.push({ n, run }); };

// Relative luminance and contrast (WCAG)
const lin = (c: number) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const lum = (r: number, g: number, b: number) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const hex = (h: string) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
const ratio = (a: number, b: number) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);

/** Text of a known color inside a box (frame px at 1920 scale): contrast against the pixels around its glyphs (2-6 px out, past the antialiasing),
 *  which is what a reader sees it on, and the glyphs' extent. */
function text(px: Px, label: string, box: Rect, ink: [number, number, number], sizePx: number, bold: boolean) {
  const [x0, y0, bw, bh] = box.map(v => Math.round(v * S)), R = Math.max(3, Math.round(6 * S)), r = Math.max(2, Math.round(2 * S));   // a ring r..R px out: past the antialiasing
  const xa = Math.max(0, x0), ya = Math.max(0, y0), xb = Math.min(px.w, x0 + bw), yb = Math.min(px.h, y0 + bh), w = xb - xa, h = yb - ya;
  const tl = lum(...ink), dist = new Float32Array(w * h), near = new Uint8Array(w * h), edge = new Uint8Array(w * h);
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, hits = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = ((ya + y) * px.w + xa + x) * 3, d = Math.hypot(px.data[i] - ink[0], px.data[i + 1] - ink[1], px.data[i + 2] - ink[2]);
    dist[y * w + x] = d;
    if (d < 48) { hits++; minX = Math.min(minX, xa + x); maxX = Math.max(maxX, xa + x); minY = Math.min(minY, ya + y); maxY = Math.max(maxY, ya + y);
      for (let dy = -R; dy <= R; dy++) for (let dx = -R; dx <= R; dx++) { const q = (y + dy) * w + x + dx; if (y + dy >= 0 && y + dy < h && x + dx >= 0 && x + dx < w) { near[q] = 1; if (Math.abs(dx) <= r && Math.abs(dy) <= r) edge[q] = 1; } } }
  }
  const bg: number[] = [];
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (near[y * w + x] && !edge[y * w + x] && dist[y * w + x] > 60) { const i = ((ya + y) * px.w + xa + x) * 3; bg.push(lum(px.data[i], px.data[i + 1], px.data[i + 2])); }
  if (!hits || !bg.length) { add(`Contrast: ${label}`, false, 'text not found in its box'); return null; }
  bg.sort((a, b) => a - b);
  const worst = tl < bg[Math.floor(bg.length / 2)] ? bg[Math.floor(bg.length * 0.05)] : bg[Math.floor(bg.length * 0.95)];   // the surround nearest the text's own luminance
  const need = bold && sizePx >= 24 ? 3 : 4.5, got = ratio(tl, worst);
  add(`Contrast: ${label}`, got >= need, `${got.toFixed(2)}:1 (needs ${need}:1, ${sizePx}px${bold ? ' bold' : ''})`);
  return { minX: minX / S, maxX: maxX / S, minY: minY / S, maxY: maxY / S };
}

const safe: Rect = [SAFE.left, SAFE.top, SCENE.width - SAFE.left - SAFE.right, SCENE.height - SAFE.top - SAFE.bottom];
const inside = (r: Rect, o: Rect, tol = 0.5) => r[0] >= o[0] - tol && r[1] >= o[1] - tol && r[0] + r[2] <= o[0] + o[2] + tol && r[1] + r[3] <= o[1] + o[3] + tol;
const fmt = (r: Rect) => `[${r.map(v => Math.round(v)).join(', ')}]`;
const cap = SCENE.presets[props.preset].caption;
const inkOf = (v: string) => hex(v.startsWith('token:') ? (color as Record<string, string>)[v.slice(6).replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())] : v);

let fastest = { v: 0, what: '' };
for (const ps of p.scenes) {
  const def = ps.def, c = CAPTURE.scenes[def.id];
  const st = (t: number): SceneTime => ({ def, t, frames: ps.frames, k: ps.k, cap: c, preset: props.preset, reduced: props.reducedMotion, frameStyle: props.frameStyle });
  // Captions and the step number: contrast on the real pixels, inside the safe area, one line that fits
  if (def.caption) {
    const cc = def.caption, words = cc.text.split(' ').length, n = ps.from + cc.start + cc.in.duration + cc.in.wordStagger * (words - 1) + 2;
    at(n, px => {
      const top = cap.baseline - 0.95 * cap.size;
      const ext = text(px, `caption "${cc.text}"`, [0, top - 10, SCENE.width, cap.size * 1.2 + 20], inkOf(cap.color), cap.size, cap.weight >= 600);
      if (ext) {
        // The brief sets the baseline on the safe line (y 1000), so descenders (g, y, p, commas) hang below it by design: the check is
        // the glyphs' sides and top, and the baseline itself
        add(`Safe area: caption ${def.id}`, ext.minX >= safe[0] - 2 && ext.maxX <= safe[0] + safe[2] && ext.minY >= safe[1] && cap.baseline <= safe[1] + safe[3],
          `glyphs x ${Math.round(ext.minX)}–${Math.round(ext.maxX)}, top ${Math.round(ext.minY)}, baseline ${cap.baseline}; descenders reach ${Math.round(ext.maxY)}`);
        add(`No clipping: caption ${def.id}`, ext.maxY - ext.minY < cap.size * 1.3 && ext.maxX < SCENE.width - SAFE.right, `one line, ${Math.round(ext.maxX - ext.minX)} px wide`);
      }
    });
  }
  if (def.hud.show) at(ps.from + Math.round(ps.frames / 2), px => { text(px, `step number ${def.id}`, [SAFE.left - 4, SAFE.top - 4, 120, 26], hex(color.muted), SCENE.hud.stepNumber.size, false); });
  if (!def.screen) continue;
  // Highlights: inside the visible screen and the safe area at the first, middle and last frame; nothing faster than the limit
  const v = viewportOf(props.preset);
  let prev: { rects: Rect[]; ptr?: [number, number]; corners: [number, number][]; scroll: number; g: ReturnType<typeof geometry> } | null = null;
  for (let t = 0; t < ps.frames; t++) {
    const g = geometry(st(t), ps.from + t), off = g.frameOffset;
    const shown = (r: Rect): Rect => { const q = toFrame(r, g.cam, v); return [q[0] + off[0], q[1] + off[1], q[2], q[3]]; };
    const rects = g.highlights.map(h => shown(h.rect));
    if (t === 0 || t === Math.floor(ps.frames / 2) || t === ps.frames - 1) {
      const screen: Rect = props.preset === 'device' ? [DEVICE.x + off[0], DEVICE.y + off[1], DEVICE.w, DEVICE.h] : [0, 0, SCENE.width, SCENE.height];
      g.highlights.forEach((h, i) => {
        add(`Safe area: ${def.id}.${h.name} @${t}`, inside(rects[i], safe), fmt(rects[i]));
        add(`No clipping: ${def.id}.${h.name} @${t}`, inside(rects[i], screen), `inside the ${props.preset === 'device' ? 'window card' : 'frame'}`);
      });
    }
    const k = v.ppt * g.cam.s, corners: [number, number][] = [[0, 0], [1, 0], [0, 1], [1, 1]].map(([a, b]) => [g.cam.cx + (a - 0.5) * v.w / k, g.cam.cy + (b - 0.5) * v.h / k]);
    const now = { rects, ptr: g.pointer && (shown([g.pointer[0], g.pointer[1], 0, 0]).slice(0, 2) as [number, number]), corners, scroll: g.scroll * k, g };
    if (prev) {
      const speeds: [number, string][] = [];
      now.rects.forEach((r, i) => prev!.g.highlights[i]?.name === g.highlights[i].name && speeds.push([Math.max(Math.hypot(r[0] - prev!.rects[i][0], r[1] - prev!.rects[i][1]), Math.hypot(r[0] + r[2] - prev!.rects[i][0] - prev!.rects[i][2], r[1] + r[3] - prev!.rects[i][1] - prev!.rects[i][3])), `${def.id}.${g.highlights[i].name}`]));
      if (now.ptr && prev.ptr) speeds.push([Math.hypot(now.ptr[0] - prev.ptr[0], now.ptr[1] - prev.ptr[1]), `${def.id} pointer`]);
      prev.corners.forEach(pt => {   // the desktop points at the view's corners: the fastest the camera moves anything
        const a = shown([pt[0], pt[1], 0, 0]), b = toFrame([pt[0], pt[1], 0, 0], prev!.g.cam, v), o = prev!.g.frameOffset;
        speeds.push([Math.hypot(a[0] - b[0] - o[0], a[1] - b[1] - o[1]), `${def.id} camera (screen edge)`]);
      });
      speeds.push([Math.abs(now.scroll - prev.scroll), `${def.id} scroll`]);
      for (const [d, what] of speeds) if (d * SCENE.fps > fastest.v) fastest = { v: d * SCENE.fps, what: `${what} @${t}` };
    }
    prev = now;
  }
}
add('Motion: fastest element', fastest.v <= SCENE.limits.maxPxPerSecond, `${Math.round(fastest.v)} px/s (${fastest.what}); limit ${SCENE.limits.maxPxPerSecond}`);
const loopHz = { 'ring pulse': 2 / ((48 / 30) || 1), 'caret blink': 1000 / (2 * SCENE.typing.caret.blinkMs), parallax: 1 / SCENE.presets.device.parallax.periodSeconds };
add('Motion: loops', Object.values(loopHz).every(h => h <= SCENE.limits.maxLoopHz), Object.entries(loopHz).map(([k, h]) => `${k} ${h.toFixed(2)} Hz`).join(', '));
// Keycaps: Ink on Porcelain keys, a fixed pair
add('Contrast: keycaps', ratio(lum(...hex(color.ink)), lum(...hex(color.surface))) >= 4.5, `${ratio(lum(...hex(color.ink)), lum(...hex(color.surface))).toFixed(2)}:1 (Ink on Porcelain)`);

// ── Brand: the hero's icon and the close's lockup against the real files; stage and wordmark colors
const fonts = JSON.parse(readFileSync(join(VIDEO, 'src/fonts.status.json'), 'utf8'));
add('Brand: Figtree', fonts.google, fonts.google ? 'Figtree and JetBrains Mono load' : `fell back: ${JSON.stringify(fonts.families)}`, fonts.google ? undefined : 'warn');
async function compare(px: Px, label: string, src: string, box: Rect) {
  const [x, y, w, h] = box.map(v => Math.round(v * S));
  const ref = await sharp(join(VIDEO, 'assets', src)).resize(w, h).ensureAlpha().raw().toBuffer();
  let sum = 0, n = 0;
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const a = (j * w + i) * 4; if (ref[a + 3] < 250) continue;
    const b = ((y + j) * px.w + x + i) * 3;
    sum += Math.abs(ref[a] - px.data[b]) + Math.abs(ref[a + 1] - px.data[b + 1]) + Math.abs(ref[a + 2] - px.data[b + 2]); n += 3;
  }
  add(`Brand: ${label}`, n > 0 && sum / n <= 6, `mean difference ${(sum / n).toFixed(2)} of 255 over ${n / 3} opaque pixels`);
}
const hero = p.scenes.find(s => s.def.id === 'hero'), close = p.scenes.find(s => s.def.id === 'close');
if (hero) at(hero.from + Math.min(90, hero.frames - 1), async px => {
  const icon = hero.def.layers.find(l => l.id === 'icon')! as unknown as { size: [number, number]; position: [number, number] };
  await compare(px, 'hero icon = Rabik_icon_1024.png', brandImages.icon.original, [...icon.position, ...icon.size] as Rect);
  const corner = [px.data[0], px.data[1], px.data[2]], cloud = hex(color.bg);
  add('Brand: stage is Cloud', corner.every((v, i) => Math.abs(v - cloud[i]) <= 4), `corner pixel rgb(${corner.join(', ')}) vs ${color.bg}`);
  // The wordmark's solid strokes: the median of its dark pixels (single pixels drift a few levels through H.264's YUV)
  const solid: number[][] = [];
  for (let y = Math.round(540 * S); y < Math.round(620 * S); y++) for (let x = Math.round(760 * S); x < Math.round(1160 * S); x++) { const i = (y * px.w + x) * 3; if (px.data[i] + px.data[i + 1] + px.data[i + 2] < 160) solid.push([px.data[i], px.data[i + 1], px.data[i + 2]]); }
  const med = [0, 1, 2].map(c => solid.map(q => q[c]).sort((a, b) => a - b)[Math.floor(solid.length / 2)] ?? 255), ink = hex(color.ink);
  add('Brand: wordmark is Ink', solid.length > 0 && med.every((v, i) => Math.abs(v - ink[i]) <= 10), `median of ${solid.length} stroke pixels rgb(${med.join(', ')}) vs ${color.ink}`);
});
if (close) at(close.from + Math.min(56, close.frames - 1), async px => {
  const lock = close.def.layers.find(l => l.id === 'lockup')! as unknown as { height: number; position: [number, number] };
  const [w0, h0] = brandImages.stacked.size, w = (w0 * lock.height) / h0;
  await compare(px, 'close lockup = Rabik_stacked_ink_transparent.png', brandImages.stacked.original, [lock.position[0] - w / 2, lock.position[1] - lock.height / 2, w, lock.height]);
});

// Pull the frames once, then run the pixel checks
const list = [...wanted.keys()].sort((a, b) => a - b);
execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-vf', `select='${list.map(n => `eq(n\\,${n})`).join('+')}'`, '-fps_mode', 'passthrough', join(TMP, 'pull%04d.png')]);
const pulled = readdirSync(TMP).filter(f => f.startsWith('pull')).sort();
for (const [i, n] of list.entries()) execFileSync('mv', [join(TMP, pulled[i]), wanted.get(n)!]);
for (const job of pending) {
  const { data, info } = await sharp(wanted.get(job.n)!).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  await job.run({ data, w: info.width, h: info.height });
}

// ── Luminance: no full-frame jump over 20 % within 3 frames
const yavg = execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-vf', 'signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-', '-f', 'null', '-'], { encoding: 'utf8', maxBuffer: 1 << 26 })
  .split('\n').filter(l => l.includes('YAVG')).map(l => Number(l.split('=')[1]));
let jump = { d: 0, n: 0 };
for (let i = 0; i + 3 < yavg.length; i++) { const d = Math.abs(yavg[i + 3] - yavg[i]) / 219; if (d > jump.d) jump = { d, n: i }; }
add('Motion: luminance', jump.d <= SCENE.limits.maxLumaChange3f, `largest 3-frame change ${(jump.d * 100).toFixed(1)} % at frame ${jump.n}; limit ${SCENE.limits.maxLumaChange3f * 100} %`);

// ── Report
const failed = rows.filter(r => !r.ok && r.level !== 'warn');
const summary = (r: typeof rows[0]) => `| ${r.ok ? 'pass' : r.level === 'warn' ? 'warn' : '**FAIL**'} | ${r.check} | ${r.detail} |`;
const grouped = new Map<string, typeof rows>();
for (const r of rows) { const key = r.check.split(':')[0]; grouped.set(key, [...(grouped.get(key) ?? []), r]); }
const md = [`## QA: ${name}.mp4`, '', `Props: \`${JSON.stringify(props)}\` · ${W}×${H} · ${frames} frames · ${failed.length ? `**${failed.length} failed**` : 'all checks pass'}`, '',
  '| Result | Check | Detail |', '|---|---|---|',
  ...[...grouped].flatMap(([k, rs]) => {
    const bad = rs.filter(r => !r.ok);
    // Repetitive per-frame geometry checks: one line when they all pass
    return ['Safe area', 'No clipping'].includes(k) && !bad.length ? [`| pass | ${k} (${rs.length} checks) | all inside |`] : rs.map(summary);
  })].join('\n');
mkdirSync(join(VIDEO, 'out/log'), { recursive: true });
writeFileSync(join(VIDEO, 'out/log', `qa-${name}.md`), md + '\n');
console.log(md);
await import('./build-log.ts');
process.exit(failed.length ? 1 : 0);
