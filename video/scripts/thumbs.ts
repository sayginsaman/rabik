// Thumbnails at 1920×1080: frame 90 (hero settled), the middle frame, and the last frame minus 15. npx tsx scripts/thumbs.ts ['<props json>']
import { join } from 'node:path';
import { plan, defaultProps } from '../src/timing.ts';
import { VIDEO, stills } from './lib/render.ts';

const props = { ...defaultProps, ...JSON.parse(process.argv[2] || '{}') }, total = plan(props).total;
const shots = [{ frame: 90, out: 'thumb_start.png' }, { frame: Math.floor(total / 2), out: 'thumb_mid.png' }, { frame: total - 15, out: 'thumb_end.png' }];
await stills(props, shots.map(s => ({ ...s, out: join(VIDEO, 'out', s.out) })), 1);
console.log(shots.map(s => `${s.out} @ frame ${s.frame}`).join('\n'));
