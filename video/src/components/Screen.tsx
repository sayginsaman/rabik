// The demo desktop under the camera, and Rabik's panels on it, all in desktop points (the capture map's units).
import { Img, staticFile } from 'remotion';
import { CAPTURE, DESK_H, DESK_W, type Panel, type Rect } from '../data';
import { camTransform, type Cam, type Viewport } from '../layout';

export const Desktop: React.FC<{ cam: Cam; viewport: Viewport; children: React.ReactNode }> = ({ cam, viewport, children }) => (
  <div style={{ position: 'absolute', left: 0, top: 0, width: DESK_W, height: DESK_H, transformOrigin: '0 0', transform: camTransform(cam, viewport) }}>
    <Img src={staticFile(CAPTURE.desktop.wallpaper)} style={{ position: 'absolute', left: 0, top: 0, width: DESK_W, height: DESK_H }} />
    {children}
  </div>
);

type Box = { x: number; y: number; w: number; h: number };
const img = (src: string, p: Box, left: number, top: number) => (
  <Img src={staticFile(src)} style={{ position: 'absolute', left, top, width: p.w, height: p.h, maxWidth: 'none' }} />
);

/** A panel as captured. A viewport panel shows `viewport.h` of it: the top and bottom stay, the middle scrolls by `scroll`. */
export const PanelImage: React.FC<{ panel: Panel | (Box & { src: string; radius?: number; viewport?: Panel['viewport'] }); scroll?: number; style?: React.CSSProperties }> = ({ panel: p, scroll = 0, style }) => {
  const vp = p.viewport;
  if (!vp) return <div style={{ position: 'absolute', left: p.x, top: p.y, width: p.w, height: p.h, ...style }}>{img(p.src, p, 0, 0)}</div>;
  const mid = vp.h - vp.fixedTop - vp.fixedBottom;
  return (
    <div style={{ position: 'absolute', left: p.x, top: p.y, width: p.w, height: vp.h, borderRadius: p.radius ?? 0, overflow: 'hidden', ...style }}>
      <div style={{ position: 'absolute', left: 0, top: vp.fixedTop, width: p.w, height: mid, overflow: 'hidden' }}>{img(p.src, p, 0, -vp.fixedTop - scroll)}</div>
      <div style={{ position: 'absolute', left: 0, top: 0, width: p.w, height: vp.fixedTop, overflow: 'hidden' }}>{img(p.src, p, 0, 0)}</div>
      {vp.fixedBottom > 0 && <div style={{ position: 'absolute', left: 0, top: vp.h - vp.fixedBottom, width: p.w, height: vp.fixedBottom, overflow: 'hidden' }}>{img(p.src, p, 0, -(p.h - vp.fixedBottom))}</div>}
    </div>
  );
};

/** One element of a panel, cut out where it sits (desktop rect); `scroll` when the panel's middle has scrolled. */
export const RegionImage: React.FC<{ src: string; panel: Box; rect: Rect; scroll?: number; scale?: number; radius?: number; style?: React.CSSProperties }> = ({ src, panel, rect: r, scroll = 0, scale = 1, radius = 0, style }) => (
  <div style={{ position: 'absolute', left: r[0], top: r[1], width: r[2], height: r[3], overflow: 'hidden', borderRadius: radius, transform: `scale(${scale})`, ...style }}>
    {img(src, panel, panel.x - r[0], panel.y - scroll - r[1])}
  </div>
);

/** Paints over a band of a panel with one of its own empty rows, stretched: the element under it is gone, the glass stays.
 *  The wallpaper goes underneath first, since a panel's glass is translucent and would otherwise be laid on twice. */
export const Patch: React.FC<{ src: string; panel: Box; rect: Rect; rowY: number; opacity?: number }> = ({ src, panel, rect: r, rowY, opacity = 1 }) => (
  <div style={{ position: 'absolute', left: r[0], top: r[1], width: r[2], height: r[3], overflow: 'hidden', opacity }}>
    <Img src={staticFile(CAPTURE.desktop.wallpaper)} style={{ position: 'absolute', left: -r[0], top: -r[1], width: DESK_W, height: DESK_H, maxWidth: 'none' }} />
    <div style={{ position: 'absolute', left: 0, top: 0, width: r[2], height: 1, overflow: 'hidden', transformOrigin: '0 0', transform: `scaleY(${r[3]})` }}>
      {img(src, panel, panel.x - r[0], -(rowY - panel.y))}
    </div>
  </div>
);
