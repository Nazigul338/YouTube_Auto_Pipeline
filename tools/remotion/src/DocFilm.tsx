import React from 'react';
import {Audio} from '@remotion/media';
import {linearTiming, TransitionSeries, type TransitionPresentation} from '@remotion/transitions';
import {clockWipe} from '@remotion/transitions/clock-wipe';
import {fade} from '@remotion/transitions/fade';
import {flip} from '@remotion/transitions/flip';
import {iris} from '@remotion/transitions/iris';
import {slide} from '@remotion/transitions/slide';
import {wipe} from '@remotion/transitions/wipe';
import {AbsoluteFill, staticFile, useVideoConfig, type CalculateMetadataFunction} from 'remotion';
import {Captions} from './scenes/Captions';
import {MapScene} from './scenes/MapScene';
import {Grain, SyncFlash, Vignette} from './scenes/Overlays';
import {QuoteScene} from './scenes/QuoteScene';
import {TitleScene} from './scenes/TitleScene';
import type {DocProps} from './types';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const presentation = (name: string, w: number, h: number): TransitionPresentation<any> => {
  switch (name) {
    case 'wipe': return wipe({direction: 'from-left'});
    case 'slide': return slide({direction: 'from-right'});
    case 'iris': return iris({width: w, height: h});
    case 'clock-wipe': return clockWipe({width: w, height: h});
    case 'flip': return flip({direction: 'from-left'});
    default: return fade();
  }
};

export const totalSeconds = (p: Pick<DocProps, 'sceneSeconds' | 'transitionSeconds'>) =>
  p.sceneSeconds.reduce((a, b) => a + b, 0) - p.transitionSeconds * (p.sceneSeconds.length - 1);

export const calculateDocMetadata: CalculateMetadataFunction<DocProps> = ({props}) => ({
  durationInFrames: Math.round(totalSeconds(props) * 30),
});

export const DocFilm: React.FC<DocProps> = (p) => {
  const {fps, width, height} = useVideoConfig();
  const tr = Math.round(p.transitionSeconds * fps);
  const [a, b, c] = p.sceneSeconds.map((s) => Math.round(s * fps));
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      <TransitionSeries>
        <TransitionSeries.Sequence name="Title" durationInFrames={a}>
          <TitleScene look={p.look} kicker={p.kicker} title={p.title} subtitle={p.subtitle} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={presentation(p.transitions[0] ?? 'fade', width, height)} timing={linearTiming({durationInFrames: tr})} />
        <TransitionSeries.Sequence name="Map" durationInFrames={b}>
          <MapScene look={p.look} seed={p.seed} title={p.mapTitle} route={p.route} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={presentation(p.transitions[1] ?? 'fade', width, height)} timing={linearTiming({durationInFrames: tr})} />
        <TransitionSeries.Sequence name="Quote" durationInFrames={c}>
          <QuoteScene look={p.look} quote={p.quote} highlight={p.highlight} lowerThird={p.lowerThird} />
        </TransitionSeries.Sequence>
      </TransitionSeries>
      <Vignette />
      <Grain strength={p.look.grain} seed={p.seed} />
      <Captions captions={p.captions} look={p.look} />
      <SyncFlash marks={p.syncMarks} />
      {p.audio ? <Audio src={staticFile(p.audio)} /> : null}
    </AbsoluteFill>
  );
};
