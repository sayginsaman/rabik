// The five curves (section 6), as cubic-béziers from scene.v1.json.
import { Easing } from 'remotion';
import { SCENE, type EaseName } from '../data';

export const ease = Object.fromEntries(Object.entries(SCENE.easing).map(([name, [a, b, c, d]]) =>
  [name, name === 'linear' ? (t: number) => t : Easing.bezier(a, b, c, d)])) as Record<EaseName, (t: number) => number>;

export const clamp01 = (t: number) => Math.min(1, Math.max(0, t));
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
/** Eased progress of a window: 0 before start, 1 after start + dur. */
export const span = (t: number, start: number, dur: number, curve: EaseName = 'linear') => ease[curve](clamp01((t - start) / Math.max(1, dur)));
