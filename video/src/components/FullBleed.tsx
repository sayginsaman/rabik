// The full-bleed preset: the screen covers the frame; a scrim darkens the bottom 360 px for the caption.
import { AbsoluteFill } from 'remotion';
import { SCENE } from '../data';

export const FullBleed: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const s = SCENE.presets.fullbleed.scrim;
  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      {children}
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: s.height, background: `linear-gradient(${s.from}, ${s.to})` }} />
    </AbsoluteFill>
  );
};
