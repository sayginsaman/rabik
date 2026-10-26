// Hero and close: brand only, on the stage. The icon's face blinks (hero), the lockup's face does its done blink (close).
import { AbsoluteFill } from 'remotion';
import { Stage } from '../components/Stage';
import { Face } from '../components/Face';
import type { LayerDef } from '../data';
import { anim } from '../motion/anim';
import { lerp, span } from '../motion/easing';
import { font } from '../theme';
import { tok } from '../tokens';
import { useScene } from './context';

const layer = (layers: LayerDef[], id: string) => layers.find(l => l.id === id)! as LayerDef & Record<string, never>;
const ASCENT = 0.95;
const Text: React.FC<{ l: LayerDef; opacity: number; dy?: number }> = ({ l, opacity, dy = 0 }) => {
  const [x, baseline] = l.position as unknown as [number, number], size = l.size as unknown as number;
  return (
    <div style={{ position: 'absolute', left: x - 960, width: 1920, top: baseline - ASCENT * size + dy, textAlign: 'center', lineHeight: 1.2, whiteSpace: 'nowrap',
      fontFamily: font[l.font as keyof typeof font], fontSize: size, fontWeight: l.weight as unknown as number, letterSpacing: (l.tracking as unknown as string) ?? 'normal',
      color: tok(l.color as unknown as string), opacity }}>{l.text as unknown as string}</div>
  );
};
const useTilt = () => {
  const s = useScene();
  if (s.reduced || s.preset !== 'device') return 'none';
  const a = anim(s, 'stage', 'tilt'), f = a.a.from as { rx: number; ry: number }, t = a.a.to as { rx: number; ry: number };
  return `perspective(1600px) rotateX(${lerp(f.rx, t.rx, a.p)}deg) rotateY(${lerp(f.ry, t.ry, a.p)}deg)`;
};

export const HeroScene: React.FC = () => {
  const s = useScene(), L = s.def.layers, icon = layer(L, 'icon'), bg = layer(L, 'bg');
  const [w] = icon.size as unknown as [number, number], [x, y] = icon.position as unknown as [number, number];
  const scale = Math.min(1.04, lerp(0.6, 1, anim(s, 'icon', 'scale').p)), blink = anim(s, 'face', 'blink');
  const word = (id: string) => ({ dy: lerp(anim(s, id, 'translateY').a.from as number, 0, anim(s, id, 'translateY').p), opacity: anim(s, id, 'opacity').p });
  return (
    <AbsoluteFill>
      <Stage glowCenter={(bg.glow as unknown as { center: [number, number] }).center} reduced={s.reduced} preset={s.preset} />
      <AbsoluteFill style={{ transform: useTilt() }}>
        <div style={{ position: 'absolute', left: x, top: y, opacity: anim(s, 'icon', 'opacity').p, transform: `scale(${scale})`, transformOrigin: 'center' }}>
          <Face image="icon" height={w} blink={blink.on && !blink.done ? blink.raw : 0} />
        </div>
        <Text l={layer(L, 'wordmark')} {...word('wordmark')} />
        <Text l={layer(L, 'line')} {...word('line')} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const CloseScene: React.FC = () => {
  const s = useScene(), L = s.def.layers, lock = layer(L, 'lockup'), bg = layer(L, 'bg');
  const h = lock.height as unknown as number, [cx, cy] = lock.position as unknown as [number, number];
  const done = anim(s, 'face', 'doneBlink');
  const smile = Math.sin(Math.PI * span(s.t, done.start, done.dur * 3));   // widens with the blink, settles back to the drawn smile
  return (
    <AbsoluteFill>
      <Stage glowCenter={(bg.glow as unknown as { center: [number, number] }).center} reduced={s.reduced} preset={s.preset} />
      <AbsoluteFill style={{ transform: useTilt() }}>
        <div style={{ position: 'absolute', left: cx, top: cy - h / 2, transform: `translateX(-50%) scale(${lerp(0.94, 1, anim(s, 'lockup', 'scale').p)})`, opacity: anim(s, 'lockup', 'opacity').p }}>
          <Face image="stacked" height={h} blink={done.on && !done.done ? done.raw : 0} smile={smile} />
        </div>
        <Text l={layer(L, 'shortcut')} opacity={anim(s, 'shortcut', 'opacity').p} />
        <Text l={layer(L, 'url')} opacity={anim(s, 'url', 'opacity').p} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
