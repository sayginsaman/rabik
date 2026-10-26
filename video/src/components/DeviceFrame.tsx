// The device preset's frame: a macOS window card (default) or a minimal MacBook bezel, around the demo desktop.
import { SCENE } from '../data';
import { DEVICE } from '../layout';
import { color, radius } from '../theme';

export const DeviceFrame: React.FC<{ style: 'mac-window' | 'macbook'; offset: [number, number]; children: React.ReactNode }> = ({ style, offset: [dx, dy], children }) => {
  const f = SCENE.presets.device.frame;
  const screen = (
    <div style={{ position: 'absolute', inset: 0, borderRadius: style === 'macbook' ? radius.sm : f.radius, overflow: 'hidden', background: color.bg }}>
      {children}
      {style === 'mac-window' && <div style={{ position: 'absolute', inset: 0, borderRadius: f.radius, boxShadow: `inset 0 0 0 1px ${color.border}`, pointerEvents: 'none' }} />}
    </div>
  );
  if (style === 'macbook') {
    const bezel = 16;
    return (
      <div style={{ position: 'absolute', left: DEVICE.x + dx - bezel, top: DEVICE.y + dy - bezel, width: DEVICE.w + bezel * 2, height: DEVICE.h + bezel * 2 }}>
        <div style={{ position: 'absolute', inset: 0, borderRadius: f.radius + bezel / 2, background: color.graphite, boxShadow: f.shadow }} />
        <div style={{ position: 'absolute', left: bezel, top: bezel, width: DEVICE.w, height: DEVICE.h }}>{screen}</div>
        <div style={{ position: 'absolute', left: -60, right: -60, top: DEVICE.h + bezel * 2 - 2, height: 14, borderRadius: '2px 2px 14px 14px', background: color.border, boxShadow: `inset 0 3px 3px ${color.surface}` }} />
      </div>
    );
  }
  return (
    <div style={{ position: 'absolute', left: DEVICE.x + dx, top: DEVICE.y + dy, width: DEVICE.w, height: DEVICE.h, borderRadius: f.radius, boxShadow: f.shadow }}>
      {screen}
    </div>
  );
};
