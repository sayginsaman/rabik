// Figtree (display, body) and JetBrains Mono (mono) from Google Fonts. scripts/check-fonts.ts records whether they can load;
// when they can't, nothing is requested and the stacks in theme.ts fall back (SF Pro Rounded / system-ui, SF Mono / Menlo).
import { loadFont as loadFigtree } from '@remotion/google-fonts/Figtree';
import { loadFont as loadMono } from '@remotion/google-fonts/JetBrainsMono';
import status from './fonts.status.json';

if (status.google) {
  loadFigtree('normal', { weights: ['500', '600', '800'], subsets: ['latin'] });
  loadMono('normal', { weights: ['500'], subsets: ['latin'] });
}
