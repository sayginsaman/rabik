// out/storyboard.md from scene.v1.json and the timing plan: each scene's id, time, screen, caption, animations and audio markers,
// with a still from the middle of the scene. npx tsx scripts/storyboard.ts ['<props json>']
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { CAPTURE, SCENE } from '../src/data.ts';
import { windowOf } from '../src/motion/anim.ts';
import { defaultProps, plan } from '../src/timing.ts';
import { VIDEO, stills } from './lib/render.ts';

const props = { ...defaultProps, ...JSON.parse(process.argv[2] || '{}') };
const p = plan(props), dir = join(VIDEO, 'out/storyboard');
mkdirSync(dir, { recursive: true });
await stills(props, p.scenes.map(s => ({ frame: s.from + Math.floor(s.frames * (s.def.id === 'hero' ? 0.6 : 0.5)), out: join(dir, `${s.def.id}.png`) })), 0.5);

const sec = (f: number) => (f / SCENE.fps).toFixed(2);
// Markers are written against the default cut (every scene at its defaultSeconds): each belongs to the scene it falls in there and
// keeps its place within that scene, stretched with it; a skipped scene's markers go with it.
let t0 = 0;
const home = SCENE.scenes.map(d => { const r = { id: d.id, start: t0, len: d.defaultSeconds }; t0 += d.defaultSeconds; return r; });
const retimed = SCENE.markers.flatMap(m => {
  const h = [...home].reverse().find(x => m.time >= x.start)!, s = p.scenes.find(x => x.def.id === h.id);
  return s ? [{ ...m, scene: h.id, time: (s.from + ((m.time - h.start) / h.len) * s.frames) / SCENE.fps }] : [];
});
const body = p.scenes.map((s, i) => {
  const st = { def: s.def, t: 0, frames: s.frames, k: s.k, cap: CAPTURE.scenes[s.def.id], preset: props.preset, reduced: props.reducedMotion, frameStyle: props.frameStyle };
  const end = s.from + s.frames, marks = retimed.filter(m => m.scene === s.def.id);
  return [`## ${i + 1}. ${s.def.id} · ${sec(s.from)}–${sec(end)} s (${s.frames} frames)`, '',
    `![${s.def.id}](storyboard/${s.def.id}.png)`, '',
    `- **Screen:** ${s.def.screen ? `${(CAPTURE.scenes[s.def.id] as { screen?: string }).screen ?? s.def.screen} (${(CAPTURE.scenes[s.def.id] as { page?: string }).page ?? 'live capture'})` : 'brand only'}`,
    `- **Caption:** ${s.def.caption ? `"${s.def.caption.text}"` : 'none'}`,
    `- **Animation:**`,
    ...s.def.animations.filter(a => !a.presetOnly || a.presetOnly === props.preset).map(a => { const w = windowOf(st, a); return `  - ${a.target} ${a.property}: frames ${w.start}–${w.start + w.dur}, ${a.easing}${a.fixed ? ', fixed' : ''}${a.note ? ` (${a.note})` : ''}`; }),
    `- **Audio markers:** ${marks.length ? marks.map(m => `${m.time.toFixed(1)} s ${m.type}: ${m.note}`).join('; ') : 'none'}`, ''].join('\n');
});
writeFileSync(join(VIDEO, 'out/storyboard.md'), `# Rabik showcase: storyboard

${props.targetSeconds} s, ${p.total} frames at ${SCENE.fps} fps, preset ${props.preset}. Generated from scene.v1.json by scripts/storyboard.ts.
Audio markers are notes only: the video has no audio track.${p.skipped.length ? `\n\nSkipped (time given to the other scenes): ${p.skipped.map(s => `**${s.id}** (${s.reason})`).join('; ')}.` : ''}
Marker times are re-timed to this cut: each keeps its place within its own scene (scene.v1.json holds them for the default 10-scene cut).

${body.join('\n')}`);
console.log('out/storyboard.md written');
