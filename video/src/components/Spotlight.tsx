// Spotlight: the element lifts (1 → 1.03, its float shadow grows) while the rest of the screen dims to 55 % around a rounded cutout.
// children: what the lifted element shows (desktop coordinates), when it is more than the panel's own pixels there.
import { DESK_H, DESK_W, type Rect } from '../data';
import { color, shadow } from '../theme';
import { RegionImage } from './Screen';

type Props = { src: string; panel: { x: number; y: number; w: number; h: number }; rect: Rect; p: number; dim: number; radius: number; scroll?: number; children?: React.ReactNode };
export const SPOT_PAD = 8;   // pt of breathing room between the element's box and the cutout
export const Spotlight: React.FC<Props> = ({ src, panel, rect: tight, p, dim, radius, scroll = 0, children }) => {
  if (p <= 0) return null;
  const r: Rect = [tight[0] - SPOT_PAD, tight[1] - SPOT_PAD, tight[2] + SPOT_PAD * 2, tight[3] + SPOT_PAD * 2];
  const rad = Math.min(radius, r[3] / 2), lift = `scale(${1 + 0.03 * p})`, origin = `${r[0] + r[2] / 2}px ${r[1] + r[3] / 2}px`;
  return (
    <>
      <div style={{ position: 'absolute', left: r[0], top: r[1], width: r[2], height: r[3], borderRadius: rad, boxShadow: `0 0 0 4000px ${color.night}`, opacity: (1 - dim) * p }} />
      <div style={{ position: 'absolute', left: r[0], top: r[1], width: r[2], height: r[3], borderRadius: rad, boxShadow: shadow.float, opacity: p, transform: lift }} />
      <div style={{ position: 'absolute', left: 0, top: 0, width: DESK_W, height: DESK_H, transformOrigin: origin, transform: lift,
        clipPath: `inset(${r[1]}px ${DESK_W - r[0] - r[2]}px ${DESK_H - r[1] - r[3]}px ${r[0]}px round ${rad}px)` }}>
        {children ?? <RegionImage src={src} panel={panel} rect={r} scroll={scroll} />}
      </div>
    </>
  );
};
