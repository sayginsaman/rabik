// Stills at chosen frames: npx tsx scripts/stills.ts '<props json>' <out dir> <frame> [frame ...]
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { stills } from './lib/render.ts';

const [props, dir, ...frames] = process.argv.slice(2);
mkdirSync(dir, { recursive: true });
await stills(JSON.parse(props || '{}'), frames.map(f => ({ frame: Number(f), out: join(dir, `f${f.padStart(4, '0')}.png`) })), 0.5);
console.log(`${frames.length} stills in ${dir}`);
