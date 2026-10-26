// The feature scenes: Rabik's real panels on the demo desktop, moved only in ways scene.v1.json describes.
import { Img, staticFile } from 'remotion';
import { Keycaps } from '../components/Keycaps';
import { Pointer, rectCenter } from '../components/Pointer';
import { Patch, PanelImage, RegionImage } from '../components/Screen';
import { Spotlight } from '../components/Spotlight';
import { TypingText } from '../components/TypingText';
import { FPS, rect, rects, type Capture, type LayerDef, type Panel, type PanelState, type Rect, type SceneDef } from '../data';
import { viewportOf } from '../layout';
import { anim } from '../motion/anim';
import { lerp, span } from '../motion/easing';
import { color, radius } from '../theme';
import { tok } from '../tokens';
import { useScene } from './context';
import { geometry } from './geometry';
import { Shell } from './Shell';

const layerOf = (s: { def: SceneDef }, id: string) => s.def.layers.find(l => l.id === id) as LayerDef & Record<string, unknown>;
const tokenRadius = (v: unknown) => (typeof v === 'string' && v.startsWith('token:radius-') ? (radius as Record<string, number>)[v.slice(13)] : radius.lg);
const union = (rs: Rect[]): Rect => {
  const x = Math.min(...rs.map(r => r[0])), y = Math.min(...rs.map(r => r[1]));
  return [x, y, Math.max(...rs.map(r => r[0] + r[2])) - x, Math.max(...rs.map(r => r[1] + r[3])) - y];
};
/** The px per desktop point at the current zoom, for things drawn in screen pixels (rings, the tap ripple). */
const usePxPerPt = (s: number) => viewportOf(useScene().preset).ppt * s;
/** A panel state's mini screen: the stand-in page, cover-fit to the mini's slot, panning down over the scene. */
const Mini: React.FC<{ cap: Capture; slot: Rect; pan: number }> = ({ cap, slot: r, pan }) => {
  const [w, h] = cap.mini!.size, k = r[2] / w, travel = Math.max(0, h * k - r[3]) * 0.45;   // down to the picks, not the page's end
  return (
    <div style={{ position: 'absolute', left: r[0], top: r[1], width: r[2], height: r[3], borderRadius: 10, overflow: 'hidden' }}>
      <Img src={staticFile(cap.mini!.src)} style={{ position: 'absolute', left: 0, top: -travel * pan, width: r[2], height: h * k, maxWidth: 'none' }} />
    </div>
  );
};

// 1 · Hold ⌃⌥Space and ask: keys go down, the box opens, the words arrive, the camera pushes in
export const AskScene: React.FC = () => {
  const s = useScene(), cap = s.cap!, geo = geometry(s, s.frame), panel = cap.panels[0], full = cap.states.full;
  const open = anim(s, 'screen', 'opacity'), ring = anim(s, 'focusRing', 'opacity'), typing = anim(s, 'typing', 'type'), keys = anim(s, 'keycaps', 'pressSequence');
  const input = rect(cap, 'input'), st = full.styles!.input, px = (k: string) => parseFloat(st[k]);
  const settle = span(s.t, typing.start + typing.dur, 6, 'easeInOutCubic');   // the typed text hands over to the captured box
  const ppt = usePxPerPt(geo.cam.s), text = layerOf(s, 'typing');
  return (
    <Shell geo={geo} overlay={<Keycaps keys={layerOf(s, 'keycaps').keys as string[]} pressAt={keys.start} stagger={2} releaseAt={typing.start + typing.dur} visibleUntil={s.frames + s.def.caption!.endOffset} />}>
      <div style={{ opacity: open.p, transform: `scale(${lerp(0.96, 1, open.p)})`, transformOrigin: `${panel.x + panel.w / 2}px ${panel.y}px` }}>
        <PanelImage panel={panel} />
        <TypingText text={text.text as string} seed={text.seed as string} t={s.t} start={typing.start} dur={typing.dur} fps={FPS} reduced={s.reduced}
          box={{ x: input[0] + px('paddingLeft'), y: input[1] + px('paddingTop'), w: input[2] - px('paddingLeft') - px('paddingRight') }} style={st} caret={st.color} />
        <PanelImage panel={full} style={{ opacity: settle }} />
        <div style={{ position: 'absolute', left: input[0], top: input[1], width: input[2], height: input[3], borderRadius: radius.md,
          boxShadow: `0 0 0 ${3 / ppt}px ${tok(layerOf(s, 'focusRing').color as string)}`, opacity: ring.p }} />
      </div>
    </Shell>
  );
};

// 2 · One clean summary: the answer card lifts out of a dimmed screen and its sections open one by one
export const SummaryScene: React.FC = () => {
  const s = useScene(), cap = s.cap!, geo = geometry(s, s.frame), panel = cap.panels[0];
  const card = rect(cap, 'summaryCard'), chips = rects(cap, 'chips'), sections = [...rects(cap, 'sections'), ...(chips.length ? [union(chips)] : [])];
  const band = union([card, ...sections]);
  const lift = anim(s, 'spot', 'lift'), fade = anim(s, 'spot', 'fadeOut'), expand = anim(s, 'summarySections', 'expandStagger');
  const reveal = (i: number) => (s.reduced ? span(s.t, expand.start, 12) : span(s.t, expand.start + i * 2, 16, 'easeOutExpo'));
  const content = (
    <>
      <Patch src={panel.src} panel={panel} rect={band} rowY={band[1] - 4} />
      {sections.map((r, i) => {
        const p = reveal(i);
        return p > 0 && <RegionImage key={i} src={panel.src} panel={panel} rect={r} style={{ opacity: p, clipPath: `inset(0 0 ${(1 - p) * 100}% 0)`, transform: `translateY(${(1 - p) * 6}px)` }} />;
      })}
    </>
  );
  return (
    <Shell geo={geo}>
      <PanelImage panel={panel} />
      {content}
      <Spotlight src={panel.src} panel={panel} rect={card} p={lift.p * (1 - fade.p)} dim={layerOf(s, 'spot').dim as number} radius={tokenRadius(layerOf(s, 'spot').radius)}>
        <RegionImage src={panel.src} panel={panel} rect={card} />
        {content}
      </Spotlight>
    </Shell>
  );
};

// 5 · Errands behind your apps: the corner chip opens, its steps come in, the mini screen pans, then it's done
export const AgentScene: React.FC = () => {
  const s = useScene(), cap = s.cap!, geo = geometry(s, s.frame), panel = cap.panels[0], done = cap.states.done;
  const chip = rect(cap, 'chip'), steps = rects(cap, 'steps');
  const scaleIn = anim(s, 'chip', 'scaleIn'), stepsIn = anim(s, 'steps', 'tickStagger'), swap = anim(s, 'done', 'crossfade'), pop = anim(s, 'doneCheck', 'pop');
  const gap = (18 / 60) * stepsIn.dur, badge = rect(done, 'badge');
  const scale = s.reduced ? 1 : Math.min(1.04, lerp(scaleIn.a.from as number, 1, scaleIn.p));
  const pan = span(s.t, stepsIn.start, s.frames - stepsIn.start, 'easeInOutCubic');
  return (
    <Shell geo={geo}>
      <div style={{ opacity: span(s.t, scaleIn.start, 6), transform: `scale(${scale})`, transformOrigin: `${chip[0] + chip[2]}px ${chip[1]}px` }}>
        <div style={{ opacity: 1 - swap.p }}>
          <PanelImage panel={panel} />
          <Mini cap={cap} slot={rect(cap, 'mini')} pan={pan} />
          <Patch src={panel.src} panel={panel} rect={union(steps)} rowY={union(steps)[1] + union(steps)[3] + 3} />
          {steps.map((r, i) => {
            const p = span(s.t, stepsIn.start + i * gap, 12, 'easeOutQuad');
            return p > 0 && <RegionImage key={i} src={panel.src} panel={panel} rect={r} style={{ opacity: p, transform: `translateX(${(1 - p) * -6}px)` }} />;
          })}
        </div>
        {swap.p > 0 && (
          <div style={{ opacity: swap.p }}>
            <PanelImage panel={done} />
            <Mini cap={cap} slot={rect(done, 'mini')} pan={pan} />
            <Patch src={done.src} panel={done} rect={badge} rowY={badge[1] - 3} />
            {pop.on && <RegionImage src={done.src} panel={done} rect={badge} radius={badge[2]} scale={Math.min(1.04, lerp(pop.a.from as number, 1, pop.p))} />}
          </div>
        )}
      </div>
    </Shell>
  );
};

// 6 · Meeting Copilot: the live transcript scrolls, slides over to the recap, and the action items tick
export const MeetingScene: React.FC = () => {
  const s = useScene(), cap = s.cap!, geo = geometry(s, s.frame), panel = cap.panels[0], recap = cap.states.recap, ticked = cap.states.ticked;
  const swap = anim(s, 'transcript->recap', 'transition'), ticks = anim(s, 'actionItems', 'tickStagger');
  const slide = s.reduced ? 0 : 40, todos = rects(recap, 'todos'), gap = (10 / 48) * ticks.dur;
  const tick = (i: number) => span(s.t, ticks.start + i * gap, 6, 'easeOutQuad');
  return (
    <Shell geo={geo}>
      {swap.p < 1 && <PanelImage panel={panel} scroll={geo.scroll} style={{ opacity: 1 - swap.p, transform: `translateX(${-slide * swap.p}px)` }} />}
      {swap.p > 0 && (
        <div style={{ opacity: swap.p, transform: `translateX(${slide * (1 - swap.p)}px)` }}>
          <PanelImage panel={recap} />
          {todos.map((r, i) => {
            const p = tick(i), popScale = 1 + 0.03 * Math.sin(Math.PI * p);
            return p > 0 && <RegionImage key={i} src={ticked.src} panel={ticked} rect={r} radius={radius.sm} style={{ opacity: p, transform: `scale(${popScale})` }} />;
          })}
          {tick(todos.length - 1) > 0 && <RegionImage src={ticked.src} panel={ticked} rect={rect(ticked, 'remind')} radius={rect(ticked, 'remind')[3] / 2} style={{ opacity: tick(todos.length - 1) }} />}
        </div>
      )}
    </Shell>
  );
};

// 7 · Safe mode: the confirm card lifts, the pointer comes to Allow and presses it
export const SafeScene: React.FC = () => {
  const s = useScene(), cap = s.cap!, geo = geometry(s, s.frame), panel = cap.panels[0];
  const card = rect(cap, 'confirmCard'), button = rect(cap, 'primaryButton');
  const lift = anim(s, 'spot', 'lift'), fade = anim(s, 'spot', 'fadeOut'), travel = anim(s, 'pointer', 'travel'), press = anim(s, 'primaryButton', 'press');
  const down = span(s.t, press.start, 4, 'easeOutQuad') * (1 - span(s.t, press.start + 4, 6, 'easeOutQuad'));
  const pressed = <RegionImage src={panel.src} panel={panel} rect={button} radius={radius.sm} scale={1 - 0.03 * down} />;
  return (
    <Shell geo={geo}>
      <PanelImage panel={panel} />
      {down > 0 && <><Patch src={panel.src} panel={panel} rect={button} rowY={button[1] - 6} />{pressed}</>}
      <Spotlight src={panel.src} panel={panel} rect={card} p={lift.p * (1 - fade.p)} dim={layerOf(s, 'spot').dim as number} radius={tokenRadius(layerOf(s, 'spot').radius)}>
        <RegionImage src={panel.src} panel={panel} rect={card} />
        {down > 0 && pressed}
      </Spotlight>
      <Pointer at={geo.pointer!} press={down} ripple={s.reduced ? 0 : span(s.t, press.start + 3, 10, 'easeOutQuad')} pxPerPt={usePxPerPt(geo.cam.s)}
        opacity={span(s.t, travel.start - 8, 8, 'easeOutQuad')} />
    </Shell>
  );
};

// 8 · The evening recap: it scrolls to the to-dos, one lifts with its source, and gets ticked
export const RecapScene: React.FC = () => {
  const s = useScene(), cap = s.cap!, geo = geometry(s, s.frame), panel = cap.panels[0], ticked = cap.states.ticked;
  const todo = geo.highlights[0].rect, lift = anim(s, 'spot', 'lift'), fade = anim(s, 'spot', 'fadeOut'), tick = anim(s, 'sourceCard', 'expand');
  const tickedRow = tick.p > 0 && (
    <RegionImage src={ticked.src} panel={ticked as PanelState & Panel} rect={todo} scroll={geo.scroll} radius={radius.sm} style={{ opacity: tick.p }} />
  );
  return (
    <Shell geo={geo}>
      <PanelImage panel={panel} scroll={geo.scroll} />
      {tickedRow}
      <Spotlight src={panel.src} panel={panel} rect={todo} scroll={geo.scroll} p={lift.p * (1 - fade.p)} dim={layerOf(s, 'spot').dim as number} radius={tokenRadius(layerOf(s, 'spot').radius)}>
        <RegionImage src={panel.src} panel={panel} rect={todo} scroll={geo.scroll} />
        {tickedRow}
      </Spotlight>
    </Shell>
  );
};

// 3, 4 · Live captures (guide, dictate; CAPTURE.md): the captured screen, its focus spotlit, the pointer tapping it
export const LiveScene: React.FC = () => {
  const s = useScene(), cap = s.cap!, geo = geometry(s, s.frame), panel = cap.panels[0], focus = rect(cap, s.def.focus!);
  const before = cap.states.before, ppt = usePxPerPt(geo.cam.s);
  const ringPulse = s.def.animations.find(a => a.property === 'pulse') ? anim(s, 'ringPulse', 'pulse') : null;
  const travel = s.def.animations.find(a => a.property === 'travel') ? anim(s, 'pointer', 'travel') : null;
  const tap = s.def.animations.find(a => a.property === 'tap') ? anim(s, 'pointer', 'tap') : null;
  const pulse = ringPulse && !s.reduced ? (ringPulse.raw * (ringPulse.a.loops ?? 1)) % 1 : 0;
  const steps = rects(cap, 'steps'), stepIn = s.def.animations.find(a => a.property === 'slideIn') ? anim(s, 'stepCaptions', 'slideIn') : null;
  const [fx, fy] = rectCenter(focus);
  return (
    <Shell geo={geo}>
      {before && <PanelImage panel={before} />}
      <PanelImage panel={panel} style={{ opacity: before ? span(s.t, 0, 12, 'easeOutQuad') : 1 }} />
      {stepIn && steps.map((r, i) => {
        const p = span(s.t, stepIn.start + i * 24 * s.k, stepIn.dur, 'easeOutQuad');
        return <RegionImage key={i} src={panel.src} panel={panel} rect={r} style={{ opacity: p, transform: `translateY(${(1 - p) * 10 / ppt}px)` }} />;
      })}
      {ringPulse && ringPulse.on && !ringPulse.done && (
        <div style={{ position: 'absolute', left: fx - focus[2] / 2, top: fy - focus[3] / 2, width: focus[2], height: focus[3], borderRadius: '50%',
          border: `${3 / ppt}px solid ${color.accent}`, opacity: lerp(1, 0.4, pulse), transform: `scale(${lerp(0.9, 1.1, pulse)})` }} />
      )}
      {travel && (
        <Pointer at={geo.pointer ?? [fx, fy]} press={tap ? span(s.t, tap.start, 3) * (1 - span(s.t, tap.start + 3, 3)) : 0}
          ripple={tap && !s.reduced ? span(s.t, tap.start + 3, 10, 'easeOutQuad') : 0} pxPerPt={ppt} opacity={span(s.t, travel.start - 8, 8)} />
      )}
    </Shell>
  );
};

export const SCENES: Record<string, React.FC> = { ask: AskScene, summary: SummaryScene, agent: AgentScene, meeting: MeetingScene, safe: SafeScene, recap: RecapScene, guide: LiveScene, dictate: LiveScene };
