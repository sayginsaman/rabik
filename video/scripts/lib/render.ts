// One bundle of src/index.ts, then stills from it: used by stills, storyboard and QA.
import { bundle } from '@remotion/bundler';
import { renderStill, selectComposition } from '@remotion/renderer';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const VIDEO = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
let served: string | null = null;
export async function serveUrl() {
  served ??= await bundle({ entryPoint: join(VIDEO, 'src/index.ts'), publicDir: join(VIDEO, 'assets'), onProgress: () => undefined });
  return served;
}
export async function stills(props: Record<string, unknown>, shots: { frame: number; out: string }[], scale = 1) {
  const url = await serveUrl();
  const composition = await selectComposition({ serveUrl: url, id: 'Showcase', inputProps: props });
  for (const s of shots) await renderStill({ composition, serveUrl: url, frame: s.frame, output: s.out, inputProps: props, scale, imageFormat: 'png' });
  return composition;
}
