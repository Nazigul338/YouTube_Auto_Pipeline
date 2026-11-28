import {Config} from '@remotion/cli/config';

// 16:9 YouTube master: H.264 + AAC, yuv420p. FFmpeg finishes the encode in the pipeline.
Config.setVideoImageFormat('jpeg');
Config.setCodec('h264');
Config.setPixelFormat('yuv420p');
Config.setOverwriteOutput(true);
