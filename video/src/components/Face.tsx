// The real icon (or stacked lockup) with its face painted out and drawn again from Rabik_face_ink.svg, so it can blink.
// blink 0..1: eyes squeeze to 10 % height and back; smile 0..1: the smile widens up to 6 % (the "done" blink).
import { Img, staticFile } from 'remotion';
import { brandImages, color, faceSvg } from '../theme';

export const Face: React.FC<{ image: keyof typeof brandImages; height: number; blink?: number; smile?: number }> = ({ image, height, blink = 0, smile = 0 }) => {
  const b = brandImages[image], k = height / b.size[1], width = b.size[0] * k;
  const squeeze = 1 - 0.9 * Math.sin(Math.PI * Math.min(1, Math.max(0, blink)));   // 1 → 0.1 → 1
  return (
    <div style={{ position: 'relative', width, height }}>
      <Img src={staticFile(b.src)} style={{ position: 'absolute', left: 0, top: 0, width, height }} />
      <svg viewBox={`0 0 ${faceSvg.width} ${faceSvg.height}`} width={faceSvg.width * b.face.scale * k} height={faceSvg.height * b.face.scale * k}
        style={{ position: 'absolute', left: b.face.x * k, top: b.face.y * k, overflow: 'visible' }}>
        <g fill={color.brandInk}>
          {faceSvg.eyes.map((e, i) => (
            <rect key={i} x={e.x} y={e.y} width={e.w} height={e.h} rx={e.w / 2} style={{ transformBox: 'fill-box', transformOrigin: 'center', transform: `scaleY(${squeeze})` }} />
          ))}
          <polygon points={faceSvg.smile} style={{ transformBox: 'fill-box', transformOrigin: 'center top', transform: `scaleX(${1 + 0.06 * smile})` }} />
        </g>
      </svg>
    </div>
  );
};
