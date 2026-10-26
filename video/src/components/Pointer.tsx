// The macOS arrow: travels on a gentle curve (control point 8 % of the distance off the line), presses, and leaves a ripple.
import type { Rect } from '../data';
import { lerp } from '../motion/easing';
import { color } from '../theme';

export const pointerPath = (from: [number, number], to: [number, number], p: number): [number, number] => {
  const [dx, dy] = [to[0] - from[0], to[1] - from[1]], d = Math.hypot(dx, dy) || 1;
  const c: [number, number] = [(from[0] + to[0]) / 2 - (dy / d) * 0.08 * d, (from[1] + to[1]) / 2 + (dx / d) * 0.08 * d];
  return [lerp(lerp(from[0], c[0], p), lerp(c[0], to[0], p), p), lerp(lerp(from[1], c[1], p), lerp(c[1], to[1], p), p)];
};

/** at: the tip in desktop points; press 0..1 (scales to 0.92); ripple 0..1 (a ring to 36 px at 30 % that fades); pxPerPt for that ring. */
export const Pointer: React.FC<{ at: [number, number]; press: number; ripple: number; pxPerPt: number; opacity?: number }> = ({ at, press, ripple, pxPerPt, opacity = 1 }) => {
  const ring = 36 / pxPerPt * ripple;
  return (
    <>
      {ripple > 0 && ripple < 1 && <div style={{ position: 'absolute', left: at[0] - ring / 2, top: at[1] - ring / 2, width: ring, height: ring, borderRadius: ring,
        border: `${2 / pxPerPt}px solid ${color.accent}`, background: `${color.accent}4D`, opacity: 1 - ripple }} />}
      <svg viewBox="0 0 22 32" width={22} height={32} style={{ position: 'absolute', left: at[0] - 1.5, top: at[1] - 1.5, opacity, transformOrigin: '1.5px 1.5px', transform: `scale(${1 - 0.08 * press})`, overflow: 'visible' }}>
        <path d="M1.5 1.5 L1.5 24.5 L7 19.3 L10.6 28 L14.4 26.4 L10.9 17.9 L18.5 17.9 Z" fill={color.ink} stroke={color.bg} strokeWidth={1.6} strokeLinejoin="round" style={{ filter: `drop-shadow(0 1px 1.5px ${color.ink}66)` }} />
      </svg>
    </>
  );
};
export const rectCenter = (r: Rect): [number, number] => [r[0] + r[2] / 2, r[1] + r[3] / 2];
