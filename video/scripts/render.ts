// A final: render with export/h264-1080p30.json, move the index to the front (faststart), run QA (exit 1 on a failure) and write
// out/metadata.json. npx tsx scripts/render.ts <name> ['<props json>']
import { execFileSync } from 'node:child_process';
import { readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { SCENE } from '../src/data.ts';
import { color } from '../src/theme.ts';
import { defaultProps, plan } from '../src/timing.ts';
import { VIDEO } from './lib/render.ts';

const [name, raw = '{}'] = process.argv.slice(2);
const preset = JSON.parse(readFileSync(join(VIDEO, 'export/h264-1080p30.json'), 'utf8'));
const out = join(VIDEO, 'out', `${name}.mp4`), tmp = join(VIDEO, 'out', `${name}.tmp.mp4`);
execFileSync('npx', ['remotion', 'render', 'src/index.ts', 'Showcase', tmp, ...preset.remotion, `--props=${raw}`], { cwd: VIDEO, stdio: ['ignore', 'ignore', 'inherit'] });
execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', tmp, '-map', '0:v', '-c', 'copy', '-an', '-movflags', '+faststart', out]);
execFileSync('rm', [tmp]);
let failed = false;
try { execFileSync('npx', ['tsx', 'scripts/qa.ts', out, raw], { cwd: VIDEO, stdio: ['ignore', 'ignore', 'inherit'] }); }
catch { failed = true; renameSync(out, out.replace('.mp4', '.FAILED-QA.mp4')); }

// metadata.json: one entry per final
const props = { ...defaultProps, ...JSON.parse(raw) }, p = plan(props), fonts = JSON.parse(readFileSync(join(VIDEO, 'src/fonts.status.json'), 'utf8'));
const used: (keyof typeof color)[] = ['bg', 'surface', 'border', 'ink', 'muted', 'haze', 'accent', 'accentText', 'night', ...(props.frameStyle === 'macbook' ? ['graphite' as const] : [])];
const metaFile = join(VIDEO, 'out/metadata.json');
let meta: Record<string, unknown> = {};
try { meta = JSON.parse(readFileSync(metaFile, 'utf8')); } catch { /* first final */ }
meta[`${name}.mp4`] = {
  qa: failed ? 'FAILED (see out/build-log.md)' : 'pass',
  preset: props.preset, frameStyle: props.frameStyle, reducedMotion: props.reducedMotion,
  duration: { seconds: props.targetSeconds, frames: p.total }, fps: SCENE.fps, resolution: [SCENE.width, SCENE.height],
  colors: used.map(token => ({ token, hex: color[token] })),
  fonts: { display: SCENE.brand.fonts.display, sans: SCENE.brand.fonts.sans, mono: SCENE.brand.fonts.mono, loaded: fonts.families,
    fallbacks: fonts.google ? [] : Object.entries(fonts.families).filter(([, v]) => v !== 'ok').map(([k]) => k),
    systemGlyphs: '⌃ and ⌥ come from the system font (not in the Latin subsets)' },
  export: preset,
  scenes: p.scenes.map(s => ({ id: s.def.id, start: s.from / SCENE.fps, seconds: s.frames / SCENE.fps, frames: s.frames, caption: s.def.caption?.text ?? null })),
  skipped: p.skipped,
};
writeFileSync(metaFile, JSON.stringify(meta, null, 1) + '\n');
console.log(`${name}: ${failed ? 'QA FAILED' : 'QA pass'}`);
process.exit(failed ? 1 : 0);
