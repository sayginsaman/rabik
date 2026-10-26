// Step number (top-left, mono) and progress dots (bottom-right) across the feature scenes.
import { useCurrentFrame } from 'remotion';
import { SCENE } from '../data';
import { span } from '../motion/easing';
import type { Plan } from '../timing';
import { color, font, radius } from '../theme';

export const Hud: React.FC<{ plan: Plan; preset: 'device' | 'fullbleed'; transition: number }> = ({ plan, preset, transition: T }) => {
  const frame = useCurrentFrame(), h = SCENE.hud, p = SCENE.presets[preset].caption;
  const steps = plan.scenes.filter(s => s.hudStep);
  if (!steps.length) return null;
  const first = steps[0], last = steps[steps.length - 1];
  const shown = span(frame, first.from - T / 2, T) * (1 - span(frame, last.from + last.frames - T / 2, T));
  if (shown <= 0) return null;
  const dot = h.progressDots, inactive = preset === 'fullbleed' ? 'rgba(255,255,255,0.4)' : dot.inactive;
  const n = steps.length, width = n * dot.size + (n - 1) * dot.gap;
  return (
    <>
      {steps.map(s => {
        const o = span(frame, s.from - T / 2, T) * (1 - span(frame, s.from + s.frames - T / 2, T));
        return o > 0 && (
          <div key={s.def.id} style={{ position: 'absolute', left: 120, top: 80, fontFamily: font.mono, fontSize: h.stepNumber.size, lineHeight: 1, color: color.muted, opacity: o * shown, letterSpacing: '0.04em',
            // full-bleed: the number sits on the screenshot, which a spotlight dims, so it gets a Cloud backing of its own
            ...(preset === 'fullbleed' ? { background: color.bg, padding: '6px 9px', margin: '-6px -9px', borderRadius: radius.sm } : {}) }}>
            {h.stepNumber.format.replace('{nn}', String(s.hudStep).padStart(2, '0')).replace('{total}', String(plan.hudTotal).padStart(2, '0'))}
          </div>
        );
      })}
      <div style={{ position: 'absolute', left: 1920 - 120 - width, top: p.baseline - 0.35 * p.size - dot.size / 2, display: 'flex', gap: dot.gap, opacity: shown }}>
        {steps.map(s => {
          const on = span(frame, s.from - T / 2, T) * (1 - span(frame, s.from + s.frames - T / 2, T));
          return <div key={s.def.id} style={{ width: dot.size, height: dot.size, borderRadius: dot.size, background: inactive, position: 'relative' }}>
            <div style={{ position: 'absolute', inset: 0, borderRadius: dot.size, background: color.accent, opacity: on }} />
          </div>;
        })}
      </div>
    </>
  );
};
