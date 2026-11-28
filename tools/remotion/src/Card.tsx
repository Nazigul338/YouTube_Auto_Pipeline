import React, {useEffect, useState} from 'react';
import {AbsoluteFill, continueRender, delayRender, Easing, interpolate, random, useCurrentFrame, useVideoConfig, type CalculateMetadataFunction} from 'remotion';
import cyr800 from '@fontsource/montserrat/files/montserrat-cyrillic-800-normal.woff2';
import lat800 from '@fontsource/montserrat/files/montserrat-latin-800-normal.woff2';

// Transparent text card that FFmpeg overlays on a shot (same slot as the HyperFrames/ASS cards in s8).
// The animation style is chosen PER VIDEO (props.style) so consecutive videos do not share one card template.
export type CardStyle = 'focus' | 'mask' | 'cascade' | 'frame';
export type CardProps = {
  readonly text: string;
  readonly dur: number;      // seconds
  readonly accent: string;   // the video's concept color
  readonly style: CardStyle;
  readonly seed: string;
};

export const calculateCardMetadata: CalculateMetadataFunction<CardProps> = ({props}) => ({
  durationInFrames: Math.max(1, Math.round(props.dur * 30)),
});

const FAMILY = 'MontserratCard';
const useMontserrat = () => {
  const [handle] = useState(() => delayRender('Montserrat font'));
  useEffect(() => {
    const faces = [
      new FontFace(FAMILY, `url(${cyr800}) format('woff2')`, {weight: '800', unicodeRange: 'U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116'}),
      new FontFace(FAMILY, `url(${lat800}) format('woff2')`, {weight: '800', unicodeRange: 'U+0000-00FF, U+2000-206F'}),
    ];
    Promise.all(faces.map((f) => f.load()))
      .then((loaded) => {
        loaded.forEach((f) => document.fonts.add(f));
        continueRender(handle);
      })
      .catch(() => continueRender(handle)); // fallback font, card still renders
  }, [handle]);
};

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const out3 = Easing.bezier(0.16, 1, 0.3, 1);

const Word: React.FC<{readonly w: string; readonly i: number; readonly n: number; readonly style: CardStyle; readonly seed: string}> = ({w, i, n, style, seed}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const stagger = Math.min(0.16, 0.9 / Math.max(1, n));
  const t0 = (0.05 + i * stagger) * fps;
  const p = interpolate(frame, [t0, t0 + 0.55 * fps], [0, 1], {...clamp, easing: out3});
  const base: React.CSSProperties = {display: 'inline-block', margin: '0 0.16em', opacity: p};
  if (style === 'focus') return <span style={{...base, filter: `blur(${(1 - p) * 12}px)`, scale: String(1.08 - 0.08 * p)}}>{w}</span>;
  if (style === 'cascade') {
    const dir = random(`${seed}-${i}`) > 0.5 ? 1 : -1;
    return <span style={{...base, translate: `0px ${(1 - p) * 60 * dir}px`, rotate: `${(1 - p) * 4 * dir}deg`}}>{w}</span>;
  }
  return <span style={{...base, translate: `0px ${(1 - p) * 40}px`}}>{w}</span>;
};

export const Card: React.FC<CardProps> = ({text, dur, accent, style, seed}) => {
  useMontserrat();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const words = text.split(/\s+/).filter(Boolean);
  const size = text.length <= 18 ? 104 : text.length <= 30 ? 92 : 80;
  const fadeOut = interpolate(frame, [Math.max(1.0, dur - 0.45) * fps, dur * fps], [1, 0], clamp);
  const line = interpolate(frame, [0.35 * fps, 0.95 * fps], [0, 1], {...clamp, easing: Easing.bezier(0.65, 0, 0.35, 1)});
  // mask: the whole line is revealed by a moving edge; frame: an accent box draws around the text
  const mask = style === 'mask' ? `inset(0 ${100 - 100 * interpolate(frame, [0.05 * fps, 0.8 * fps], [0, 1], {...clamp, easing: out3})}% 0 0)` : undefined;
  return (
    <AbsoluteFill style={{backgroundColor: 'transparent', opacity: fadeOut}}>
      <div style={{position: 'absolute', left: '50%', top: '40%', translate: '-50% -50%', width: 1500, textAlign: 'center'}}>
        <div
          style={{
            display: 'inline-block', position: 'relative', padding: style === 'frame' ? '18px 40px' : 0,
            fontFamily: `${FAMILY}, Montserrat, 'DejaVu Sans', sans-serif`, fontWeight: 800, fontSize: size, lineHeight: 1.12,
            color: '#ffffff', textShadow: '0 6px 30px rgba(0,0,0,0.6), 0 2px 4px rgba(0,0,0,0.65)', clipPath: mask,
          }}
        >
          {style === 'frame' ? (
            <>
              {/* top/bottom rules grow from the center, side rules from the middle: a box drawn around the thought */}
              <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 5, backgroundColor: accent, scale: `${line} 1`}} />
              <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 5, backgroundColor: accent, scale: `${line} 1`}} />
              <div style={{position: 'absolute', top: 0, bottom: 0, left: 0, width: 5, backgroundColor: accent, scale: `1 ${line}`}} />
              <div style={{position: 'absolute', top: 0, bottom: 0, right: 0, width: 5, backgroundColor: accent, scale: `1 ${line}`}} />
            </>
          ) : null}
          {words.map((w, i) => (
            <Word key={i} w={w} i={i} n={words.length} style={style} seed={seed} />
          ))}
        </div>
        {style !== 'frame' ? (
          <div style={{margin: '26px auto 0', width: 420, height: 6, borderRadius: 3, backgroundColor: accent, scale: `${line} 1`, boxShadow: '0 0 18px rgba(0,0,0,0.35)'}} />
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
