import React from 'react';
import {AbsoluteFill, random, useCurrentFrame, useVideoConfig} from 'remotion';

// Film grain: an SVG noise field whose seed changes every frame (real grain flickers, a static texture does not).
export const Grain: React.FC<{readonly strength: number; readonly seed: string}> = ({strength, seed}) => {
  const frame = useCurrentFrame();
  if (strength <= 0) return null;
  const s = Math.floor(random(`${seed}-grain-${frame}`) * 1000);
  return (
    <AbsoluteFill style={{opacity: 0.18 * strength, mixBlendMode: 'overlay', pointerEvents: 'none'}}>
      <svg width="100%" height="100%">
        <filter id={`g${s}`}>
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={s} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter={`url(#g${s})`} />
      </svg>
    </AbsoluteFill>
  );
};

export const Vignette: React.FC = () => (
  <AbsoluteFill
    style={{background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,0.55) 100%)', pointerEvents: 'none'}}
  />
);

// TEST ONLY: a 2-frame white patch in the top-left corner at each mark; the self-test matches it to audio beeps.
export const SyncFlash: React.FC<{readonly marks: number[]}> = ({marks}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const on = marks.some((m) => frame >= Math.round(m * fps) && frame < Math.round(m * fps) + 2);
  if (!on) return null;
  return <div style={{position: 'absolute', left: 0, top: 0, width: 64, height: 64, backgroundColor: '#ffffff'}} />;
};
