import React, {useMemo} from 'react';
import type {Caption} from '@remotion/captions';
import {AbsoluteFill, Easing, interpolate, Sequence, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Look} from '../types';

// Professional subtitles: short pages, the spoken word lights up in the video's accent color,
// safe area at the bottom, dark backing for readability on any shot.
const Page: React.FC<{readonly tokens: {text: string; fromMs: number; toMs: number}[]; readonly startMs: number; readonly look: Look}> = ({
  tokens, startMs, look,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const nowMs = startMs + (frame / fps) * 1000;
  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 90}}>
      <div
        style={{
          fontFamily: look.font, fontSize: 54, fontWeight: 700, padding: '10px 26px', borderRadius: 10,
          backgroundColor: 'rgba(0,0,0,0.55)', whiteSpace: 'pre', maxWidth: 1500, textAlign: 'center',
          opacity: interpolate(frame, [0, 4], [0, 1], {extrapolateRight: 'clamp'}),
          translate: `0px ${interpolate(frame, [0, 6], [14, 0], {extrapolateRight: 'clamp', easing: Easing.bezier(0.16, 1, 0.3, 1)})}px`,
        }}
      >
        {tokens.map((t, i) => (
          <span key={i} style={{color: nowMs >= t.fromMs && nowMs < t.toMs ? look.accent : look.ink}}>
            {t.text}
          </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};

type Tok = {text: string; fromMs: number; toMs: number};

// Own pagination (≤4 words, a new page after a pause or a sentence end) so two sentences never share a page
// and a page disappears when its last word ends.
export const paginate = (captions: Caption[], maxWords = 4, gapMs = 250): Tok[][] => {
  const pages: Tok[][] = [];
  let cur: Tok[] = [];
  for (const c of captions) {
    const prev = cur[cur.length - 1];
    const brk = prev && (c.startMs - prev.toMs > gapMs || /[.!?…]$/.test(prev.text.trim()) || cur.length >= maxWords);
    if (brk) {
      pages.push(cur);
      cur = [];
    }
    cur.push({text: cur.length ? ` ${c.text.trim()}` : c.text.trim(), fromMs: c.startMs, toMs: c.endMs});
  }
  if (cur.length) pages.push(cur);
  return pages;
};

export const Captions: React.FC<{readonly captions: Caption[]; readonly look: Look}> = ({captions, look}) => {
  const {fps} = useVideoConfig();
  const pages = useMemo(() => paginate(captions), [captions]);
  return (
    <>
      {pages.map((p, i) => {
        const startMs = p[0].fromMs;
        const endMs = Math.min(p[p.length - 1].toMs + 200, pages[i + 1]?.[0].fromMs ?? Infinity);
        const from = Math.round((startMs / 1000) * fps);
        const dur = Math.max(1, Math.round((endMs / 1000) * fps) - from);
        return (
          <Sequence key={i} name={`Caption ${i + 1}`} from={from} durationInFrames={dur} layout="none">
            <Page tokens={p} startMs={startMs} look={look} />
          </Sequence>
        );
      })}
    </>
  );
};
