import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Look} from '../types';

const Letter: React.FC<{readonly ch: string; readonly delay: number; readonly look: Look}> = ({ch, delay, look}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = (frame - delay) / fps;
  return (
    <span
      style={{
        display: 'inline-block',
        whiteSpace: 'pre',
        opacity: interpolate(t, [0, 0.5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
        filter: `blur(${interpolate(t, [0, 0.7], [14, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}px)`,
        translate: `0px ${interpolate(t, [0, 0.8], [26, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
          easing: Easing.bezier(0.16, 1, 0.3, 1),
        })}px`,
        color: look.ink,
      }}
    >
      {ch}
    </span>
  );
};

export const TitleScene: React.FC<{
  readonly look: Look;
  readonly kicker: string;
  readonly title: string;
  readonly subtitle: string;
}> = ({look, kicker, title, subtitle}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const ease = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
  return (
    <AbsoluteFill style={{backgroundColor: look.bg, overflow: 'hidden', fontFamily: look.font}}>
      {/* slow documentary push-in on a lit backdrop */}
      <AbsoluteFill
        style={{
          scale: String(interpolate(frame, [0, durationInFrames], [1, 1.09])),
          background: `radial-gradient(circle at 30% 35%, ${look.accent}55 0%, ${look.bg} 55%, #000 100%)`,
        }}
      />
      <AbsoluteFill style={{justifyContent: 'center', padding: '0 180px'}}>
        <div
          style={{
            fontSize: 30,
            letterSpacing: 10,
            textTransform: 'uppercase',
            color: look.accent,
            opacity: interpolate(frame, [0.2 * fps, 1 * fps], [0, 1], ease),
          }}
        >
          {kicker}
        </div>
        <div style={{fontSize: 108, fontWeight: 800, lineHeight: 1.05, marginTop: 18}}>
          {[...title].map((ch, i) => (
            <Letter key={i} ch={ch} delay={Math.round(0.6 * fps + i * 1.2)} look={look} />
          ))}
        </div>
        <div
          style={{
            height: 6,
            marginTop: 30,
            backgroundColor: look.accent,
            width: interpolate(frame, [1.4 * fps, 2.6 * fps], [0, 520], {...ease, easing: Easing.bezier(0.65, 0, 0.35, 1)}),
          }}
        />
        <div
          style={{
            fontSize: 42,
            marginTop: 30,
            color: look.ink,
            opacity: interpolate(frame, [2.2 * fps, 3.2 * fps], [0, 0.85], ease),
          }}
        >
          {subtitle}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
