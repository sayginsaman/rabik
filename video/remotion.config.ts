// Renders read screens and brand files from assets/ (npm run theme, capture and normalize make them); H.264 with no audio track.
import { Config } from '@remotion/cli/config';

Config.setPublicDir('./assets');
Config.setVideoImageFormat('png');
Config.setCodec('h264');
Config.setMuted(true);
