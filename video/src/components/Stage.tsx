// The stage: Cloud with a soft Haze glow (device preset, and the brand scenes in both presets).
import { AbsoluteFill, useCurrentFrame } from 'remotion';
import { SCENE } from '../data';
import { drift } from '../layout';
import { color } from '../theme';

export const Stage: React.FC<{ glowCenter?: [number, number]; reduced: boolean; preset: 'device' | 'fullbleed' }> = ({ glowCenter = [960, 520], reduced, preset }) => {
  const frame = useCurrentFrame();
  const { glow } = SCENE.presets.device.stage, amp = reduced ? 0 : SCENE.presets[preset].parallax.background;
  const [x, y] = [glowCenter[0] + drift(frame, amp, 0.7), glowCenter[1] + drift(frame, amp * 0.6, 2.1)];
  return (
    <AbsoluteFill style={{ background: color.bg }}>
      <AbsoluteFill style={{ opacity: glow.opacity, background: `radial-gradient(circle ${glow.radius}px at ${x}px ${y}px, ${color.haze} 0%, ${color.haze}00 100%)` }} />
    </AbsoluteFill>
  );
};
