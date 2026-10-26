import { createContext, useContext } from 'react';
import type { SceneTime } from '../motion/anim';

/** The scene being drawn: its local time t (0 = its first frame), length, stretch k, preset and capture. */
export const SceneContext = createContext<(SceneTime & { frame: number }) | null>(null);
export function useScene() {
  const s = useContext(SceneContext);
  if (!s) throw new Error('useScene outside a scene');
  return s;
}
