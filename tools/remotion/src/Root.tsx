import React from 'react';
import {Composition} from 'remotion';
import {Card, calculateCardMetadata} from './Card';
import {calculateDocMetadata, DocFilm} from './DocFilm';

// One registration; every real video passes its own props (look, text, route, transitions, captions) from the
// pipeline's per-video edit concept, so the output is never a fixed template.
export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="DocTest"
      component={DocFilm}
      durationInFrames={450}
      fps={30}
      width={1920}
      height={1080}
      calculateMetadata={calculateDocMetadata}
      defaultProps={{
        seed: 'doc-test-1',
        look: {bg: '#0e1116', ink: '#f2ede4', accent: '#d9a441', grain: 0.8, font: 'DejaVu Sans, Arial, sans-serif'},
        kicker: 'Silicon Valley · 1983',
        title: 'The Spreadsheet War',
        subtitle: 'How one program changed the office forever',
        mapTitle: 'From Cambridge to every desk',
        route: [
          {x: 0.28, y: 0.38, label: 'Cambridge'},
          {x: 0.52, y: 0.56, label: 'New York'},
          {x: 0.74, y: 0.42, label: 'The world'},
        ],
        quote: 'Software became the reason to buy a computer.',
        highlight: 'reason',
        lowerThird: 'Remotion render test · 16:9 · 30 fps',
        transitions: ['iris', 'wipe'],
        sceneSeconds: [5.5, 5.5, 5],
        transitionSeconds: 0.5,
        captions: [
          {text: 'In', startMs: 600, endMs: 900, timestampMs: 750, confidence: null},
          {text: ' 1983,', startMs: 900, endMs: 1700, timestampMs: 1300, confidence: null},
          {text: ' one', startMs: 1700, endMs: 2100, timestampMs: 1900, confidence: null},
          {text: ' program', startMs: 2100, endMs: 2800, timestampMs: 2450, confidence: null},
          {text: ' changed', startMs: 2800, endMs: 3400, timestampMs: 3100, confidence: null},
          {text: ' everything.', startMs: 3400, endMs: 4600, timestampMs: 4000, confidence: null},
          {text: 'It', startMs: 6200, endMs: 6500, timestampMs: 6350, confidence: null},
          {text: ' spread', startMs: 6500, endMs: 7200, timestampMs: 6850, confidence: null},
          {text: ' city', startMs: 7200, endMs: 7700, timestampMs: 7450, confidence: null},
          {text: ' by', startMs: 7700, endMs: 8000, timestampMs: 7850, confidence: null},
          {text: ' city.', startMs: 8000, endMs: 9200, timestampMs: 8600, confidence: null},
          {text: 'And', startMs: 11000, endMs: 11400, timestampMs: 11200, confidence: null},
          {text: ' the', startMs: 11400, endMs: 11700, timestampMs: 11550, confidence: null},
          {text: ' office', startMs: 11700, endMs: 12300, timestampMs: 12000, confidence: null},
          {text: ' never', startMs: 12300, endMs: 12800, timestampMs: 12550, confidence: null},
          {text: ' looked', startMs: 12800, endMs: 13300, timestampMs: 13050, confidence: null},
          {text: ' back.', startMs: 13300, endMs: 14600, timestampMs: 13950, confidence: null},
        ],
        audio: null,
        syncMarks: [],
      }}
    />
    <Composition
      id="Card"
      component={Card}
      durationInFrames={90}
      fps={30}
      width={1920}
      height={1080}
      calculateMetadata={calculateCardMetadata}
      defaultProps={{text: 'Похвала — не приговор', dur: 3, accent: '#f2c14e', style: 'focus' as const, seed: 'card-test'}}
    />
  </>
);
