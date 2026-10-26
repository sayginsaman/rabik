// Where things sit in the 1920×1080 frame, and the camera over the 1152×720 pt demo desktop.
import { DESK_H, DESK_W, SCENE, center, type Rect } from './data';
import { lerp } from './motion/easing';

export const VIDEO = { w: SCENE.width, h: SCENE.height };
export const SAFE = SCENE.safeArea;
/** The device preset's window card: 16:10 like the desktop, inside the 1440×900 maximum, centered across, above the captions. */
export const DEVICE = { x: 360, y: 96, w: 1200, h: 750 };
export const FULLBLEED_BASE = 1.02;   // a little overscan so the full-bleed screen can drift without showing an edge

export type Viewport = { x: number; y: number; w: number; h: number; ppt: number };
export const viewportOf = (preset: 'device' | 'fullbleed'): Viewport => preset === 'device'
  ? { ...DEVICE, ppt: DEVICE.w / DESK_W }
  : { x: 0, y: 0, w: VIDEO.w, h: VIDEO.h, ppt: Math.max(VIDEO.w / DESK_W, VIDEO.h / DESK_H) };

/** s: zoom over the fitted desktop; cx, cy: the desktop point at the middle of the view. */
export type Cam = { s: number; cx: number; cy: number };
const clamp = (v: number, lo: number, hi: number) => (lo > hi ? (lo + hi) / 2 : Math.min(hi, Math.max(lo, v)));
export function clampCam(c: Cam, v: Viewport): Cam {
  const hw = v.w / (2 * v.ppt * c.s), hh = v.h / (2 * v.ppt * c.s);
  return { s: c.s, cx: clamp(c.cx, hw, DESK_W - hw), cy: clamp(c.cy, hh, DESK_H - hh) };
}
/** Device: the whole desktop. Full-bleed: cover, centered on the focus as far as the desktop allows. */
export function baseCam(preset: 'device' | 'fullbleed', focus: Rect): Cam {
  const v = viewportOf(preset), [fx, fy] = center(focus);
  return preset === 'device' ? clampCam({ s: 1, cx: DESK_W / 2, cy: DESK_H / 2 }, v) : clampCam({ s: FULLBLEED_BASE, cx: fx, cy: fy }, v);
}
/** Push in toward the focus: zoom to `to` times the base, the view's middle moving onto the focus. */
export function pushCam(base: Cam, focus: Rect, to: number, p: number, v: Viewport): Cam {
  const [fx, fy] = center(focus);
  return clampCam({ s: base.s * lerp(1, to, p), cx: lerp(base.cx, fx, p), cy: lerp(base.cy, fy, p) }, v);
}
export const camTransform = (c: Cam, v: Viewport) => `translate(${v.w / 2}px, ${v.h / 2}px) scale(${v.ppt * c.s}) translate(${-c.cx}px, ${-c.cy}px)`;
/** A desktop rect in frame pixels (before the device frame's drift). */
export function toFrame(r: Rect, c: Cam, v: Viewport): Rect {
  const k = v.ppt * c.s;
  return [v.x + v.w / 2 + (r[0] - c.cx) * k, v.y + v.h / 2 + (r[1] - c.cy) * k, r[2] * k, r[3] * k];
}
/** Parallax: a slow sine, one period per presets.*.parallax.periodSeconds. */
export const drift = (frame: number, amp: number, phase = 0) =>
  amp * Math.sin((2 * Math.PI * frame) / (SCENE.presets.device.parallax.periodSeconds * SCENE.fps) + phase);
