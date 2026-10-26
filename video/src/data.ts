// The two files the video is built from: scene.v1.json (what happens) and capture-map.json (where the real UI is).
import sceneJson from '../scene.v1.json';
import captureJson from '../assets/screens/capture-map.json';

export type Rect = [number, number, number, number];
export type EaseName = 'easeOutQuad' | 'easeInOutCubic' | 'easeOutExpo' | 'easeOutBackSoft' | 'linear';
export type AnimDef = {
  target: string; property: string; from: unknown; to: unknown; start: number; duration: number; easing: EaseName; fixed: boolean;
  presetOnly?: string; note?: string; loops?: number; maxTravel?: number; toward?: string; style?: string;
};
export type CaptionDef = { text: string; start: number; endOffset: number; in: { duration: number; easing: EaseName; rise: number; wordStagger: number };
  out: { duration: number; easing: EaseName; rise: number } };
export type LayerDef = { id: string; type: string; [k: string]: unknown };
export type SceneDef = {
  id: string; index: number; defaultSeconds: number; weight: number; minSeconds: number; maxSeconds: number; screen: string | null;
  focus?: string; layers: LayerDef[]; animations: AnimDef[]; caption: CaptionDef | null; hud: { show: boolean; step?: number };
};
export type Panel = { id: string; src: string; x: number; y: number; w: number; h: number; radius: number;
  viewport?: { h: number; fixedTop: number; fixedBottom: number } };
export type PanelState = { id: string; src: string; x: number; y: number; w: number; h: number; regions: Record<string, Rect | Rect[]>;
  styles?: Record<string, Record<string, string>> };
export type Capture = {
  status: 'captured' | 'needs-live-capture' | 'brand-only'; reason?: string; focus?: string; screen?: string;
  panels: Panel[]; regions: Record<string, Rect | Rect[]>; styles: Record<string, Record<string, string>>; states: Record<string, PanelState>;
  mini?: { src: string; size: [number, number] };
};

export const SCENE = sceneJson as unknown as Omit<typeof sceneJson, 'scenes' | 'easing'> & { scenes: SceneDef[]; easing: Record<EaseName, [number, number, number, number]> };
export const CAPTURE = captureJson as unknown as { desktop: { size: [number, number]; scale: number; wallpaper: string }; scenes: Record<string, Capture> };
export const FPS = SCENE.fps;
export const [DESK_W, DESK_H] = CAPTURE.desktop.size;

export const rect = (c: Capture | PanelState, name: string): Rect => {
  const r = c.regions[name];
  if (!r || Array.isArray(r[0])) throw new Error(`Region "${name}" is missing or a list`);
  return r as Rect;
};
export const rects = (c: Capture | PanelState, name: string): Rect[] => (c.regions[name] as Rect[] | undefined) ?? [];
export const center = (r: Rect): [number, number] => [r[0] + r[2] / 2, r[1] + r[3] / 2];
