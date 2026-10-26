import { color } from './theme';

/** "token:accent-text" → its color from theme.ts; anything else as written. */
export const tok = (v: string): string =>
  v.startsWith('token:') ? (color as Record<string, string>)[v.slice(6).replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())] : v;
