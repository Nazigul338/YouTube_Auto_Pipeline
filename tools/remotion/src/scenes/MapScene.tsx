import React, {useMemo} from 'react';
import {AbsoluteFill, Easing, interpolate, random, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Look, MapPoint} from '../types';

// A stylized, procedural "archive map": coastline and grid are generated from the video's seed, so every video
// gets its own geography sketch. No map tiles / API keys / logos are needed.
// Smooth seeded landmass outline (sum of low-frequency waves), drawn as a closed Catmull-Rom curve.
const land = (seed: string, cx: number, cy: number, rx: number, ry: number) => {
  const n = 64;
  const ph = [0, 1, 2, 3].map((k) => random(`${seed}-p${k}`) * Math.PI * 2);
  const pts: [number, number][] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const r = 1 + 0.16 * Math.sin(2 * a + ph[0]) + 0.1 * Math.sin(3 * a + ph[1]) + 0.06 * Math.sin(5 * a + ph[2])
      + 0.035 * Math.sin(9 * a + ph[3]);
    pts.push([cx + rx * r * Math.cos(a), cy + ry * r * Math.sin(a)]);
  }
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < n; i++) {
    const p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
    d += ` C${p1[0] + (p2[0] - p0[0]) / 6},${p1[1] + (p2[1] - p0[1]) / 6} ${p2[0] - (p3[0] - p1[0]) / 6},${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]},${p2[1]}`;
  }
  return d + ' Z';
};

const lands = (seed: string, w: number, h: number) =>
  [0, 1, 2].map((k) => land(`${seed}-l${k}`,
    w * (0.22 + 0.3 * k + 0.08 * random(`${seed}-x${k}`)), h * (0.45 + 0.15 * (random(`${seed}-y${k}`) - 0.5)),
    w * (0.12 + 0.06 * random(`${seed}-w${k}`)), h * (0.2 + 0.08 * random(`${seed}-h${k}`))));

const Marker: React.FC<{readonly p: MapPoint; readonly at: number; readonly look: Look; readonly W: number; readonly H: number}> = ({
  p, at, look, W, H,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pop = spring({frame: frame - at, fps, config: {damping: 14, mass: 0.6}});
  return (
    <g transform={`translate(${p.x * W} ${p.y * H})`}>
      <circle r={34 * pop} fill="none" stroke={look.accent} strokeWidth={2} opacity={1 - pop * 0.6} />
      <circle r={11 * pop} fill={look.accent} />
      <text x={22} y={-20} fontSize={36} fill={look.ink} opacity={pop} fontFamily={look.font}>
        {p.label}
      </text>
    </g>
  );
};

export const MapScene: React.FC<{readonly look: Look; readonly seed: string; readonly title: string; readonly route: MapPoint[]}> = ({
  look, seed, title, route,
}) => {
  const frame = useCurrentFrame();
  const {fps, width: W, height: H, durationInFrames} = useVideoConfig();
  const shores = useMemo(() => lands(seed, W, H), [seed, W, H]);
  const path = route.map((p, i) => `${i ? 'L' : 'M'}${p.x * W},${p.y * H}`).join(' ');
  let len = 0;
  for (let i = 1; i < route.length; i++) len += Math.hypot((route[i].x - route[i - 1].x) * W, (route[i].y - route[i - 1].y) * H);
  const draw = interpolate(frame, [0.6 * fps, 3.6 * fps], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.45, 0, 0.2, 1),
  });
  const ease = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
  return (
    <AbsoluteFill style={{backgroundColor: look.bg, fontFamily: look.font, overflow: 'hidden'}}>
      <AbsoluteFill
        style={{
          // slow camera drift across the map
          scale: String(interpolate(frame, [0, durationInFrames], [1.12, 1.0])),
          translate: `${interpolate(frame, [0, durationInFrames], [-40, 30])}px 0px`,
        }}
      >
        <svg width={W} height={H}>
          {Array.from({length: 13}).map((_, i) => (
            <line key={`v${i}`} x1={(i * W) / 12} y1={0} x2={(i * W) / 12} y2={H} stroke={look.ink} strokeOpacity={0.07} />
          ))}
          {Array.from({length: 8}).map((_, i) => (
            <line key={`h${i}`} x1={0} y1={(i * H) / 7} x2={W} y2={(i * H) / 7} stroke={look.ink} strokeOpacity={0.07} />
          ))}
          {shores.map((d, i) => (
            <g key={i}>
              <path d={d} fill="none" stroke={look.accent} strokeOpacity={0.12} strokeWidth={18} />
              <path d={d} fill={look.ink} fillOpacity={0.05} stroke={look.ink} strokeOpacity={0.45} strokeWidth={1.6} />
            </g>
          ))}
          <path
            d={path}
            fill="none"
            stroke={look.accent}
            strokeWidth={6}
            style={{filter: `drop-shadow(0 0 10px ${look.accent})`}}
            strokeLinecap="round"
            strokeDasharray={`${len} ${len}`}
            strokeDashoffset={len * (1 - draw)}
          />
          {route.map((p, i) => (
            <Marker key={i} p={p} at={Math.round((0.6 + (3 * i) / Math.max(1, route.length - 1)) * fps)} look={look} W={W} H={H} />
          ))}
        </svg>
      </AbsoluteFill>
      <div
        style={{
          position: 'absolute', left: 120, top: 90, fontSize: 54, fontWeight: 700, color: look.ink,
          opacity: interpolate(frame, [0, 0.6 * fps], [0, 1], ease),
          translate: `${interpolate(frame, [0, 0.8 * fps], [-30, 0], {...ease, easing: Easing.bezier(0.16, 1, 0.3, 1)})}px 0px`,
        }}
      >
        {title}
      </div>
    </AbsoluteFill>
  );
};
