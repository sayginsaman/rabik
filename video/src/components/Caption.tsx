// One idea per scene: bottom-left, baseline at y 1000; words rise in 2 frames apart, the line rises away at the end.
import { SCENE, type CaptionDef } from '../data';
import { span } from '../motion/easing';
import { useScene } from '../scenes/context';
import { font } from '../theme';
import { tok } from '../tokens';

const ASCENT = 0.95;   // Figtree's ascender (em), with line-height 1.2 the baseline sits this far below the box top
export const captionTop = (size: number) => SCENE.presets.device.caption.baseline - ASCENT * size;

export const Caption: React.FC<{ caption: CaptionDef }> = ({ caption: c }) => {
  const s = useScene(), p = SCENE.presets[s.preset].caption;
  const end = s.frames + c.endOffset, outStart = end - c.out.duration;
  if (s.t < c.start || s.t >= end) return null;
  const out = span(s.t, outStart, c.out.duration, c.out.easing), rise = s.reduced ? 0 : 1;
  return (
    <div style={{ position: 'absolute', left: p.x, top: captionTop(p.size), maxWidth: 1920 - p.x * 2, whiteSpace: 'nowrap', fontFamily: font.display, fontSize: p.size,
      fontWeight: p.weight, lineHeight: 1.2, letterSpacing: '-0.01em', color: tok(p.color),
      opacity: 1 - out, transform: `translateY(${-c.out.rise * out * rise}px)` }}>
      {c.text.split(' ').map((w, i) => {
        const q = span(s.t, c.start + i * c.in.wordStagger, c.in.duration, c.in.easing);
        return <span key={i} style={{ display: 'inline-block', marginRight: '0.26em', opacity: q, transform: `translateY(${c.in.rise * (1 - q) * rise}px)` }}>{w}</span>;
      })}
    </div>
  );
};
