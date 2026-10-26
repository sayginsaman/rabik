import { Composition } from 'remotion';
import { Showcase } from './components/SceneRenderer';
import { SCENE } from './data';
import { defaultProps, plan, type ShowcaseProps } from './timing';

// --props='{"preset":"fullbleed"}', '{"targetSeconds":30}', '{"reducedMotion":true}', '{"frameStyle":"macbook"}',
// '{"scenes":{"recap":{"enabled":false}}}': the length always comes out at targetSeconds × 30 frames.
export const Root: React.FC = () => (
  <Composition id="Showcase" component={Showcase as React.FC<Record<string, unknown>>} width={SCENE.width} height={SCENE.height} fps={SCENE.fps}
    durationInFrames={plan(defaultProps).total} defaultProps={defaultProps as unknown as Record<string, unknown>}
    calculateMetadata={({ props }) => ({ durationInFrames: plan(props as Partial<ShowcaseProps>).total })} />
);
