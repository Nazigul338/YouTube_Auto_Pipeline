import type {Caption} from '@remotion/captions';

// Every value is chosen per video (topic, edit concept), so the same component never yields the same film twice.
export type Look = {
  readonly bg: string;       // base color of the scene world
  readonly ink: string;      // main text color
  readonly accent: string;   // the video's own accent color
  readonly grain: number;    // 0..1 film grain strength
  readonly font: string;     // CSS font stack
};

export type MapPoint = {readonly x: number; readonly y: number; readonly label: string};

export type DocProps = {
  readonly seed: string;
  readonly look: Look;
  readonly kicker: string;      // small line above the title (era / place)
  readonly title: string;
  readonly subtitle: string;
  readonly mapTitle: string;
  readonly route: MapPoint[];   // normalized 0..1 coordinates
  readonly quote: string;
  readonly highlight: string;   // word(s) inside quote to highlight
  readonly lowerThird: string;
  readonly transitions: string[]; // per cut: fade | wipe | slide | iris | clock-wipe | flip
  readonly sceneSeconds: number[]; // length of each of the 3 scenes (before transition overlap)
  readonly transitionSeconds: number;
  readonly captions: Caption[];
  readonly audio: string | null;  // file in public/ (FFmpeg-made mix), or null
  readonly syncMarks: number[];   // seconds: test-only flash markers matched to audio beeps
};
