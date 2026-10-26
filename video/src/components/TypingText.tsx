// Text typing into a real field, in the field's own captured font and caret geometry (ui.html's .q.live::after): seeded rhythm, a solid caret while typing that blinks every
// 530 ms once idle. Reduced motion: the whole text fades in over 12 frames.
import { SCENE } from '../data';
import { span } from '../motion/easing';
import { typedCount, typingSchedule } from '../motion/typing';

type Props = {
  text: string; seed: string; t: number; start: number; dur: number; fps: number; reduced: boolean;
  box: { x: number; y: number; w: number }; style: Record<string, string>; caret: string;
  /** Dictation's Clean up: this part fades and its gap closes, 0..1 */
  strike?: { part: string; p: number };
};

export const TypingText: React.FC<Props> = ({ text, seed, t, start, dur, fps, reduced, box, style, caret, strike }) => {
  const ms = ((t - start) / fps) * 1000;
  const schedule = typingSchedule(text, seed, (dur / fps) * 1000);
  const n = reduced ? (t >= start ? text.length : 0) : typedCount(schedule, ms);
  const typing = !reduced && n > 0 && n < text.length;
  const idleFor = ms - (schedule[schedule.length - 1] ?? 0);
  const blinkOn = typing || n === 0 || Math.floor(Math.max(0, idleFor) / SCENE.typing.caret.blinkMs) % 2 === 0;
  let shown: React.ReactNode = text.slice(0, n);
  if (strike && n === text.length) {
    const i = text.indexOf(strike.part);
    shown = <>{text.slice(0, i)}<span style={{ display: 'inline-block', whiteSpace: 'pre', overflow: 'hidden', verticalAlign: 'bottom', opacity: 1 - strike.p,
      maxWidth: `${(1 - strike.p) * strike.part.length}ch`, textDecoration: strike.p > 0 ? 'line-through' : 'none' }}>{strike.part}</span>{text.slice(i + strike.part.length)}</>;
  }
  return (
    <div style={{ position: 'absolute', left: box.x, top: box.y, width: box.w, fontFamily: style.fontFamily, fontSize: style.fontSize, fontWeight: style.fontWeight as never,
      lineHeight: style.lineHeight, letterSpacing: style.letterSpacing, color: style.color, opacity: reduced ? span(t, start, 12) : 1, overflowWrap: 'anywhere' }}>
      {shown}
      {t >= start && <span style={{ display: 'inline-block', width: SCENE.typing.caret.width, height: '1em', marginLeft: 2, verticalAlign: -2, background: caret, opacity: blinkOn ? 1 : 0 }} />}
    </div>
  );
};
