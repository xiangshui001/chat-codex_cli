export type LibraryView = 'outside' | 'entrance' | 'reading' | 'gallery' | 'upper' | 'tour';
export interface CameraWaypoint {
  position: [number, number, number];
  target: [number, number, number];
  /** Seconds to move from the preceding point. Ignored on the first point. */
  duration?: number;
  floor?: 0 | 1 | 2;
  label?: string;
}
export interface CameraSample {
  position: [number, number, number];
  target: [number, number, number];
  floor: 0 | 1 | 2;
  label: string;
  progress: number;
}
export interface CameraPath {
  points: CameraWaypoint[];
  duration: number;
  sample(seconds: number): CameraSample;
}
export const LIBRARY_CAMERA_PATHS: Record<Exclude<LibraryView, 'outside'>, CameraWaypoint[]>;
export function createCameraPath(points: CameraWaypoint[]): CameraPath;
export interface LibraryState {
  mode: 'outside' | 'inside';
  floor: 0 | 1 | 2;
  position: [number, number, number];
  yaw: number; pitch: number;
  cutaway: boolean; night: boolean;
  /** Alias of pathPlaying, retained for state readers from version 1. */
  transitioning: boolean;
  paused: boolean;
  path: string | null;
  pathLabel: string;
  pathPlaying: boolean;
  pathProgress: number;
  pathDuration: number;
  voxels: number; books: number; drawCalls: number;
}
export interface Voxel {
  x: number; y: number; z: number;
  w: number; h: number; d: number;
  c: string;
  type: 'normal' | 'metal' | 'glass' | 'glow';
  layer: 'roof' | 'shell' | 'interior';
  rot: number;
}
export interface Architecture {
  root: any; roof: any; shell: any; inside: any;
  voxelData: Voxel[];
  floorHeights: number[];
  stats: {voxels: number; books: number; drawCalls: number};
  /** Authoring helper. The camera viewer does not use walking collision logic. */
  sampleFloor(x: number, z: number, previousY: number): {y: number; level: number; stairs: boolean} | null;
  setCutaway(value: boolean): void;
  update(dt: number): void;
  dispose(): void;
}
export interface LibraryOptions {
  onStateChange?: (state: LibraryState) => void;
  /** Only Space and Escape are handled. Defaults to the focused canvas. */
  keyboard?: 'focus' | 'global' | 'off';
  cameraPaths?: Record<string, CameraWaypoint[]>;
  maxPixelRatio?: number;
  shadows?: boolean;
  frameOffset?: number;
}
export interface LibraryInstance {
  enter(view?: Exclude<LibraryView, 'outside'>): void;
  exterior(): void;
  playPath(name?: string): void;
  pausePath(): void;
  resumePath(): void;
  seekPath(progress: number): void;
  setCameraPath(name: string, waypoints: CameraWaypoint[]): void;
  setCutaway(value: boolean): void;
  setNight(value: boolean): void;
  /** Pause the path and rotate the camera without translating it. */
  turn(deltaYaw: number, deltaPitch?: number): void;
  getState(): LibraryState;
  /** Pause/resume rendering, also freezing the camera timeline. */
  pause(): void;
  resume(): void;
  dispose(): void;
  scene: any; camera: any; building: Architecture;
}
export function mountLibrary(host: HTMLElement, options?: LibraryOptions): LibraryInstance;
export function buildArchitecture(scene: any): Architecture;
export class TisuLibraryElement extends HTMLElement {
  readonly api: LibraryInstance | null;
  getState(): LibraryState | null;
  setView(view: LibraryView): void;
  enter(view?: Exclude<LibraryView, 'outside'>): void;
  exterior(): void;
  playPath(name?: string): void;
  setCameraPath(name: string, waypoints: CameraWaypoint[]): void;
  pausePath(): void;
  resumePath(): void;
  seekPath(progress: number): void;
  setNight(value: boolean): void;
  setCutaway(value: boolean): void;
  pause(): void;
  resume(): void;
}
export function defineLibraryElement(tagName?: string): boolean;
declare global {
  interface HTMLElementTagNameMap {'tisu-library': TisuLibraryElement;}
  interface HTMLElementEventMap {
    'library-state-change': CustomEvent<LibraryState>;
    'library-error': CustomEvent<{message: string}>;
  }
}
