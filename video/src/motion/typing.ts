// Seeded typing (section 6): 35-70 ms per character, +180 ms after , . ? !, +90 ms after a space one time in five.
// The same seed gives the same rhythm on every render.
import { SCENE } from '../data';

function rng(seed: string) {
  let h = 1779033703 ^ seed.length;
  for (let i = 0; i < seed.length; i++) { h = Math.imul(h ^ seed.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); }
  return () => {   // mulberry32
    h = (h + 0x6d2b79f5) | 0; let t = Math.imul(h ^ (h >>> 15), 1 | h);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** When each character lands, in ms from the first key; squeezed evenly when it would overrun `withinMs`. */
export function typingSchedule(text: string, seed: string, withinMs = Infinity): number[] {
  const c = SCENE.typing, next = rng(seed), out: number[] = [];
  let ms = 0;
  for (let i = 0; i < text.length; i++) {
    ms += c.msPerCharMin + next() * (c.msPerCharMax - c.msPerCharMin);
    out.push(ms);
    if (',.?!'.includes(text[i])) ms += c.punctuationPauseMs;
    else if (text[i] === ' ' && next() < c.spacePauseChance) ms += c.spacePauseMs;
  }
  const end = out[out.length - 1] ?? 0;
  return end > withinMs ? out.map(t => (t * withinMs) / end) : out;
}
export const typedCount = (schedule: number[], ms: number) => { let n = 0; while (n < schedule.length && schedule[n] <= ms) n++; return n; };
