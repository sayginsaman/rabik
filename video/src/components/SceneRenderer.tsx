// Reads scene.v1.json through the timing plan: one Sequence per scene, overlapping its neighbours by half a transition each side
// (crossfade, a 24 px slide in the travel direction, the outgoing scene easing to 0.98; reduced motion: a plain 24-frame crossfade).
import { useMemo } from 'react';
import { AbsoluteFill, Sequence, useCurrentFrame } from 'remotion';
import { CAPTURE, SCENE } from '../data';
import { clamp01, ease } from '../motion/easing';
import { SceneContext } from '../scenes/context';
import { CloseScene, HeroScene } from '../scenes/Brand';
import { SCENES } from '../scenes/Features';
import { defaultProps, plan, type PlannedScene, type ShowcaseProps } from '../timing';
import { Hud } from './Hud';
import { Stage } from './Stage';
import '../fonts';

const COMPONENTS: Record<string, React.FC> = { hero: HeroScene, close: CloseScene, ...SCENES };

const SceneLayer: React.FC<{ ps: PlannedScene; first: boolean; last: boolean; pre: number; T: number; nextCovers: boolean; props: ShowcaseProps }> =
  ({ ps, first, last, pre, T, nextCovers, props }) => {
    const t = useCurrentFrame() - pre, Comp = COMPONENTS[ps.def.id], reduced = props.reducedMotion;
    const inP = first ? 1 : ease.easeInOutCubic(clamp01((t + T / 2) / T));
    const outP = last ? 0 : ease.easeInOutCubic(clamp01((t - (ps.frames - T / 2)) / T));
    const move = reduced ? 0 : 1;
    const style: React.CSSProperties = {
      opacity: inP * (nextCovers ? 1 : 1 - outP),
      transform: `translateX(${(24 * (1 - inP) - 24 * outP) * move}px) scale(${1 - 0.02 * outP * move})`,
    };
    const value = { def: ps.def, t, frames: ps.frames, k: ps.k, cap: CAPTURE.scenes[ps.def.id], preset: props.preset, reduced, frameStyle: props.frameStyle, frame: ps.from + t };
    return (
      <SceneContext.Provider value={value}>
        <AbsoluteFill style={style}><Comp /></AbsoluteFill>
      </SceneContext.Provider>
    );
  };

export const Showcase: React.FC<Partial<ShowcaseProps>> = input => {
  const props = { ...defaultProps, ...input };
  const p = useMemo(() => plan(props), [JSON.stringify(props)]);
  const T = props.reducedMotion ? SCENE.reducedMotion.transition.durationFrames : SCENE.timing.transition.durationFrames;
  const covers = (i: number) => props.preset === 'fullbleed' && !!p.scenes[i]?.def.screen;   // a full-bleed screen hides what's under it
  return (
    <AbsoluteFill>
      <Stage reduced={props.reducedMotion} preset={props.preset} />
      {p.scenes.map((ps, i) => {
        const first = i === 0, last = i === p.scenes.length - 1, pre = first ? 0 : T / 2, post = last ? 0 : T / 2;
        return (
          <Sequence key={ps.def.id} from={ps.from - pre} durationInFrames={ps.frames + pre + post} name={ps.def.id}>
            <SceneLayer ps={ps} first={first} last={last} pre={pre} T={T} nextCovers={covers(i) && covers(i + 1)} props={props} />
          </Sequence>
        );
      })}
      <Hud plan={p} preset={props.preset} transition={T} />
    </AbsoluteFill>
  );
};
