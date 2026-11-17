import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execBinary } from './ffmpeg.js';
import type { TtsOptions, TtsResult } from './types.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const TTS_SCRIPT = resolve(__dirname, '..', 'scripts', 'tts.py');

/**
 * Synthesize speech audio using Edge TTS (via Python edge-tts).
 */
export async function synthesizeSpeech(options: TtsOptions): Promise<TtsResult> {
  const python = options.pythonPath ?? 'python';
  const audioPath = resolve(options.outputPath);

  const args: string[] = [
    TTS_SCRIPT,
    '--text',
    options.text,
    '--output',
    audioPath,
    '--voice',
    options.voice ?? 'en-US-AndrewMultilingualNeural',
    '--rate',
    options.rate ?? '+0%',
    '--pitch',
    options.pitch ?? '+0Hz',
  ];

  let timingsPath: string | undefined;
  if (options.timingsPath) {
    timingsPath = resolve(options.timingsPath);
    args.push('--timings', timingsPath);
  }

  await execBinary(python, args);
  return { audioPath, timingsPath };
}
