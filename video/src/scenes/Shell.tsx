// A feature scene's frame: the demo desktop under the camera, in the device card or full-bleed, with its caption and keys.
import { AbsoluteFill } from 'remotion';
import { Caption } from '../components/Caption';
import { DeviceFrame } from '../components/DeviceFrame';
import { FullBleed } from '../components/FullBleed';
import { Desktop } from '../components/Screen';
import { viewportOf } from '../layout';
import { useScene } from './context';
import type { Geometry } from './geometry';

export const Shell: React.FC<{ geo: Geometry; overlay?: React.ReactNode; children: React.ReactNode }> = ({ geo, overlay, children }) => {
  const s = useScene(), v = viewportOf(s.preset);
  const desk = <Desktop cam={geo.cam} viewport={v}>{children}</Desktop>;
  return (
    <AbsoluteFill>
      {s.preset === 'device' ? <DeviceFrame style={s.frameStyle} offset={geo.frameOffset}>{desk}</DeviceFrame> : <FullBleed>{desk}</FullBleed>}
      {overlay}
      {s.def.caption && <Caption caption={s.def.caption} />}
    </AbsoluteFill>
  );
};
