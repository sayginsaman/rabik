// How long each scene runs for a target length (section 8): weights, clamped to each scene's min and max, the rest spread over the
// unclamped ones, whole frames with the remainder on the last scene. Scenes switched off, or whose screen isn't captured, drop out
// and their time goes to the others by weight.
import { CAPTURE, FPS, SCENE, type SceneDef } from './data';

export type ShowcaseProps = {
  preset: 'device' | 'fullbleed';
  targetSeconds: number;
  reducedMotion: boolean;
  frameStyle: 'mac-window' | 'macbook';
  scenes: Record<string, { enabled?: boolean }>;
};
export const defaultProps: ShowcaseProps = { preset: 'device', targetSeconds: SCENE.timing.targetSeconds, reducedMotion: false, frameStyle: 'mac-window', scenes: {} };

export type PlannedScene = { def: SceneDef; from: number; frames: number; k: number; hudStep: number | null };
export type Plan = { total: number; scenes: PlannedScene[]; skipped: { id: string; reason: string }[]; hudTotal: number; warnings: string[] };

export function plan(input: Partial<ShowcaseProps>): Plan {
  const props = { ...defaultProps, ...input };
  const T = props.targetSeconds, { minTargetSeconds: lo, maxTargetSeconds: hi } = SCENE.timing;
  if (!(T >= lo && T <= hi)) throw new Error(`targetSeconds must be ${lo} to ${hi}, got ${T}`);
  const skipped: Plan['skipped'] = [], warnings: string[] = [];
  const active = SCENE.scenes.filter(s => {
    if (props.scenes[s.id]?.enabled === false) { skipped.push({ id: s.id, reason: 'disabled by props' }); return false; }
    const cap = CAPTURE.scenes[s.id];
    if (s.screen && cap?.status !== 'captured') { skipped.push({ id: s.id, reason: cap?.reason ?? 'screen not captured' }); return false; }
    return true;
  });
  const secs = new Map<string, number>(), clamped = new Set<string>();
  for (let pass = 0; pass <= active.length; pass++) {
    const free = active.filter(s => !clamped.has(s.id));
    const left = T - active.filter(s => clamped.has(s.id)).reduce((n, s) => n + secs.get(s.id)!, 0);
    const weight = free.reduce((n, s) => n + s.weight, 0);
    let changed = false;
    for (const s of free) {
      const v = (left * s.weight) / weight;
      if (v < s.minSeconds || v > s.maxSeconds) { secs.set(s.id, Math.min(s.maxSeconds, Math.max(s.minSeconds, v))); clamped.add(s.id); changed = true; }
      else secs.set(s.id, v);
    }
    if (!changed || !free.length) break;
  }
  // Every scene at its max (or min) and time still left over: spread it by weight past the limits rather than onto one scene
  const short = T - active.reduce((n, s) => n + secs.get(s.id)!, 0), all = active.reduce((n, s) => n + s.weight, 0);
  if (Math.abs(short) > 1 / FPS) {
    for (const s of active) secs.set(s.id, secs.get(s.id)! + (short * s.weight) / all);
    warnings.push(`${short > 0 ? 'Every scene is at its maximum' : 'Every scene is at its minimum'}: ${Math.abs(short).toFixed(2)} s spread over all scenes by weight, past their ${short > 0 ? 'max' : 'min'}`);
  }
  const total = Math.round(T * FPS);
  let from = 0, step = 0;
  const hudTotal = active.filter(s => s.hud.show).length;
  const scenes = active.map((def, i) => {
    const frames = i === active.length - 1 ? total - from : Math.round(secs.get(def.id)! * FPS);
    const p: PlannedScene = { def, from, frames, k: frames / Math.round(def.defaultSeconds * FPS), hudStep: def.hud.show ? ++step : null };
    from += frames;
    return p;
  });
  return { total, scenes, skipped, hudTotal, warnings };
}
