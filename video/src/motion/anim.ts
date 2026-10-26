// A scene's animations from scene.v1.json, timed for this render: non-fixed ones stretch with the scene (k = its frames over its
// default), fixed ones keep their frame counts; a negative start counts back from the scene's end.
import type { AnimDef, Capture, SceneDef } from '../data';
import { clamp01, ease } from './easing';

export type SceneTime = {
  def: SceneDef; t: number; frames: number; k: number; cap: Capture | undefined;
  preset: 'device' | 'fullbleed'; reduced: boolean; frameStyle: 'mac-window' | 'macbook';
};

export function windowOf(s: SceneTime, a: AnimDef) {
  const dur = a.fixed ? a.duration : Math.max(1, Math.round(a.duration * s.k));
  const start = a.start < 0 ? s.frames + (a.fixed ? a.start : Math.round(a.start * s.k)) : Math.round(a.start * s.k);
  return { start, dur };
}
export function find(s: SceneTime, target: string, property: string): AnimDef {
  const a = s.def.animations.find(x => x.target === target && x.property === property);
  if (!a) throw new Error(`${s.def.id}: no "${target}.${property}" animation in scene.v1.json`);
  return a;
}
/** Eased (p) and linear (raw) progress of one animation at this frame, with its window. */
export function anim(s: SceneTime, target: string, property: string) {
  const a = find(s, target, property), w = windowOf(s, a), raw = clamp01((s.t - w.start) / w.dur);
  return { ...w, a, raw, p: ease[a.easing](raw), on: s.t >= w.start, done: s.t >= w.start + w.dur };
}
