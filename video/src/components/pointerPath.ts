// The pointer's path, shared with scripts/qa.ts: a quadratic curve whose control point sits 8 % of the distance off the line.
import type { Rect } from '../data';
import { lerp } from '../motion/easing';

export const pointerPath = (from: [number, number], to: [number, number], p: number): [number, number] => {
  const [dx, dy] = [to[0] - from[0], to[1] - from[1]], d = Math.hypot(dx, dy) || 1;
  const c: [number, number] = [(from[0] + to[0]) / 2 - (dy / d) * 0.08 * d, (from[1] + to[1]) / 2 + (dx / d) * 0.08 * d];
  return [lerp(lerp(from[0], c[0], p), lerp(c[0], to[0], p), p), lerp(lerp(from[1], c[1], p), lerp(c[1], to[1], p), p)];
};
export const rectCenter = (r: Rect): [number, number] => [r[0] + r[2] / 2, r[1] + r[3] / 2];
