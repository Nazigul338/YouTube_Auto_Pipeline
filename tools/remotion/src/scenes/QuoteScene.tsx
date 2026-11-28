import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Look} from '../types';

const Word: React.FC<{readonly w: string; readonly at: number; readonly hot: boolean; readonly look: Look}> = ({w, at, hot, look}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const ease = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
  return (
    <span style={{position: 'relative', display: 'inline-block', marginRight: 22}}>
      {hot ? (
        <span
          style={{
            position: 'absolute', left: -8, right: -8, bottom: 6, height: '42%', backgroundColor: look.accent,
            transformOrigin: 'left', scale: `${interpolate(frame, [at + 0.4 * fps, at + 0.9 * fps], [0, 1], {...ease, easing: Easing.bezier(0.65, 0, 0.35, 1)})} 1`,
          }}
        />
      ) : null}
      <span
        style={{
          position: 'relative', color: look.ink,
          opacity: interpolate(frame, [at, at + 0.35 * fps], [0, 1], ease),
          filter: `blur(${interpolate(frame, [at, at + 0.4 * fps], [8, 0], ease)}px)`,
        }}
      >
        {w}
      </span>
    </span>
  );
};

export const QuoteScene: React.FC<{readonly look: Look; readonly quote: string; readonly highlight: string; readonly lowerThird: string}> = ({
  look, quote, highlight, lowerThird,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const hot = new Set(highlight.toLowerCase().split(/\s+/).filter(Boolean));
  const words = quote.split(/\s+/).filter(Boolean);
  const ease = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
  return (
    <AbsoluteFill style={{backgroundColor: look.bg, fontFamily: look.font}}>
      <AbsoluteFill style={{background: `linear-gradient(120deg, #000 0%, ${look.bg} 50%, ${look.accent}33 100%)`}} />
      <AbsoluteFill style={{justifyContent: 'center', padding: '0 200px'}}>
        <div style={{fontSize: 76, fontWeight: 700, lineHeight: 1.25}}>
          {words.map((w, i) => (
            <Word key={i} w={w} at={Math.round(0.3 * fps + i * 0.18 * fps)} hot={hot.has(w.toLowerCase().replace(/[.,!?«»"]/g, ''))} look={look} />
          ))}
        </div>
      </AbsoluteFill>
      <div
        style={{
          position: 'absolute', left: 120, bottom: 230, padding: '16px 28px', backgroundColor: '#000000aa',
          borderLeft: `6px solid ${look.accent}`, color: look.ink, fontSize: 34,
          // fully off-screen before it slides in (a fixed -700px left the tail of a long label visible)
          translate: `calc(${interpolate(frame, [2 * fps, 2.7 * fps], [1, 0], {...ease, easing: Easing.bezier(0.16, 1, 0.3, 1)})} * (-100% - 160px)) 0px`,
        }}
      >
        {lowerThird}
      </div>
    </AbsoluteFill>
  );
};
