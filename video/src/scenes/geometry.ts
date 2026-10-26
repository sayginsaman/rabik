// Each scene's camera, scroll and highlight boxes at a frame: pure, so the renderer and scripts/qa.ts agree on where things are.
import { rect, rects, type Capture, type Panel, type Rect } from '../data';
import { pointerPath, rectCenter } from '../components/pointerPath';
import { baseCam, clampCam, drift, pushCam, viewportOf, type Cam } from '../layout';
import { anim, type SceneTime } from '../motion/anim';
import { SCENE } from '../data';

export type Geometry = {
  cam: Cam;
  /** The device card's drift in frame px (device preset); full-bleed drifts the camera instead. */
  frameOffset: [number, number];
  scroll: number;
  highlights: { name: string; rect: Rect }[];
  /** The pointer's tip (desktop points), when the scene has one */
  pointer?: [number, number];
};

export const mainPanel = (cap: Capture): Panel => cap.panels[0];
/** A viewport panel's scroll range: from the top until `untilY` (panel y) reaches the bottom of the scrolling part. */
const maxScroll = (p: Panel, untilY: number) => Math.max(0, untilY - (p.viewport!.h - p.viewport!.fixedBottom));

export function meetingScroll(s: SceneTime) {
  const cap = s.cap!, p = mainPanel(cap), lines = rect(cap, 'lines');
  const max = maxScroll(p, lines[1] - p.y + lines[3]);
  return max * anim(s, 'transcript', 'scroll').p;
}
/** The recap scrolls until its first to-do sits a third of the way down the box (as far as the content allows). */
export function recapScroll(s: SceneTime) {
  const cap = s.cap!, p = mainPanel(cap), todo = rect(cap, 'todo');
  const target = Math.min(maxScroll(p, p.h), Math.max(0, todo[1] - p.y - p.viewport!.h / 3));
  return target * anim(s, 'screen', 'scroll').p;
}

/** "focus:confirmCard.offset(180,160)" (screen px from its center) or "focus:confirmCard.primaryButton" (that element's center). */
export function anchor(cap: Capture, spec: string, pxPerPt: number): [number, number] {
  const m = spec.match(/^focus:(\w+)(?:\.offset\((-?\d+),(-?\d+)\)|\.(\w+))?$/);
  if (!m) throw new Error(`Bad anchor ${spec}`);
  if (m[4]) return rectCenter(rect(cap, m[4]));
  const [x, y] = rectCenter(rect(cap, m[1]));
  return [x + Number(m[2] ?? 0) / pxPerPt, y + Number(m[3] ?? 0) / pxPerPt];
}

export function geometry(s: SceneTime, frame: number): Geometry {
  const cap = s.cap!, v = viewportOf(s.preset), par = s.reduced ? 0 : SCENE.presets[s.preset].parallax.frame;
  const sway = (c: Cam): Cam => (s.preset === 'fullbleed' && par ? clampCam({ ...c, cx: c.cx + drift(frame, par, 0) / v.ppt, cy: c.cy + drift(frame, par * 0.6, 1.3) / v.ppt }, v) : c);
  const frameOffset: [number, number] = s.preset === 'device' && par ? [drift(frame, par, 0), drift(frame, par * 0.6, 1.3)] : [0, 0];
  const push = (focus: Rect) => {
    const base = baseCam(s.preset, focus), a = anim(s, 'camera', 'pushIn');
    return sway(s.reduced ? base : pushCam(base, focus, a.a.to as number, a.p, v));
  };
  const p = cap.panels[0];
  switch (s.def.id) {
    case 'ask': { const box = rect(cap, 'box'); return { cam: push(box), frameOffset, scroll: 0, highlights: [{ name: 'box', rect: box }, { name: 'input', rect: rect(cap, 'input') }] }; }
    case 'summary': { const card = rect(cap, 'summaryCard'); return { cam: push(card), frameOffset, scroll: 0, highlights: [{ name: 'summaryCard', rect: card }] }; }
    case 'agent': {
      const chip = rect(cap, 'chip'), done = s.t >= anim(s, 'done', 'crossfade').start;
      return { cam: push(chip), frameOffset, scroll: 0, highlights: [done ? { name: 'chipDone', rect: rect(cap.states.done, 'chip') } : { name: 'chip', rect: chip }] };
    }
    case 'meeting': {
      const scroll = meetingScroll(s), after = s.t >= anim(s, 'transcript->recap', 'transition').start;
      const live: Rect = [p.x, p.y, p.w, p.viewport!.h], recap = cap.states.recap;
      return { cam: sway(baseCam(s.preset, live)), frameOffset, scroll, highlights: [{ name: after ? 'recap' : 'transcript', rect: after ? [recap.x, recap.y, recap.w, recap.h] : live }] };
    }
    case 'safe': {
      const card = rect(cap, 'confirmCard'), cam = sway(baseCam(s.preset, card)), pl = s.def.layers.find(l => l.id === 'pointer')!;
      const pointer = pointerPath(anchor(cap, pl.from as string, v.ppt * cam.s), anchor(cap, pl.to as string, v.ppt * cam.s), anim(s, 'pointer', 'travel').p);
      return { cam, frameOffset, scroll: 0, highlights: [{ name: 'confirmCard', rect: card }], pointer };
    }
    case 'recap': {
      const scroll = recapScroll(s), todo = rect(cap, 'todo');
      return { cam: sway(baseCam(s.preset, [p.x, p.y, p.w, p.viewport!.h])), frameOffset, scroll, highlights: [{ name: 'todo', rect: [todo[0], todo[1] - scroll, todo[2], todo[3]] }] };
    }
    default: {   // live captures (guide, dictate): the focus box from their capture JSON
      const focus = rect(cap, s.def.focus!), cam = sway(baseCam(s.preset, focus)), pl = s.def.layers.find(l => l.type === 'pointer');
      const travel = s.def.animations.find(a => a.target === 'pointer' && a.property === 'travel');
      const pointer = pl && travel ? pointerPath(anchor(cap, pl.from as string, v.ppt * cam.s), anchor(cap, pl.to as string, v.ppt * cam.s), anim(s, 'pointer', 'travel').p) : undefined;
      return { cam, frameOffset, scroll: 0, highlights: [{ name: s.def.focus!, rect: focus }, ...rects(cap, 'steps').map(r => ({ name: 'step', rect: r }))], pointer };
    }
  }
}
