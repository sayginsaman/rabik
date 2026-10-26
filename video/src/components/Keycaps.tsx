// Keys above the caption (⌃ ⌥ Space, or fn): pressed in sequence, held while Rabik listens, then let go.
import { useCurrentFrame } from 'remotion';
import { SCENE } from '../data';
import { drift } from '../layout';
import { span } from '../motion/easing';
import { useScene } from '../scenes/context';
import { color, font, radius } from '../theme';
import { captionTop } from './Caption';

export const KEYCAP_H = 56;
export const Keycaps: React.FC<{ keys: string[]; pressAt: number; stagger: number; releaseAt: number; visibleUntil: number }> = ({ keys, pressAt, stagger, releaseAt, visibleUntil }) => {
  const s = useScene(), frame = useCurrentFrame();
  const amp = s.reduced ? 0 : SCENE.presets[s.preset].parallax.overlay;
  const top = captionTop(SCENE.presets[s.preset].caption.size) - 22 - KEYCAP_H + drift(frame, amp * 0.5, 2.4);
  const fade = span(s.t, 0, 8, 'easeOutQuad') * (1 - span(s.t, visibleUntil - 9, 9, 'easeInOutCubic'));
  return (
    <div style={{ position: 'absolute', left: SCENE.presets[s.preset].caption.x, top, display: 'flex', gap: 10, opacity: fade }}>
      {keys.map((k, i) => {
        const down = span(s.t, pressAt + i * stagger, 3, 'easeOutQuad') * (1 - span(s.t, releaseAt, 4, 'easeOutQuad'));
        return (
          <div key={k} style={{ height: KEYCAP_H, minWidth: KEYCAP_H, padding: k.length > 1 ? '0 22px' : 0, boxSizing: 'border-box', display: 'flex', alignItems: 'center',
            justifyContent: k.length > 2 ? 'flex-start' : 'center', borderRadius: radius.sm, background: color.surface, border: `1px solid ${color.border}`,
            boxShadow: `0 ${3 - 2 * down}px 0 ${color.border}`, transform: `translateY(${2 * down}px) scale(${1 - 0.08 * down})`,
            fontFamily: font.mono, fontSize: k.length > 1 ? 22 : 26, fontWeight: 500, color: color.ink, width: k === 'Space' ? 150 : undefined }}>{k}</div>
        );
      })}
    </div>
  );
};
