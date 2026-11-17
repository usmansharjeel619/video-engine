import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execBinary } from './ffmpeg.js';
import type { WhisperOptions, WhisperTranscript } from './types.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const TRANSCRIBE_SCRIPT = resolve(__dirname, '..', 'scripts', 'transcribe.py');

/**
 * Transcribe audio or video with faster-whisper and return word-level timestamps.
 */
export async function transcribeWithWhisper(options: WhisperOptions): Promise<WhisperTranscript> {
  const python = options.pythonPath ?? 'python';
  const inputPath = resolve(options.inputPath);

  const args: string[] = [
    TRANSCRIBE_SCRIPT,
    '--input',
    inputPath,
    '--model',
    options.model ?? 'base',
    '--device',
    options.device ?? 'auto',
    '--compute-type',
    options.computeType ?? 'int8',
  ];

  if (options.language) {
    args.push('--language', options.language);
  }
  if (options.outputJsonPath) {
    args.push('--output-json', resolve(options.outputJsonPath));
  }
  if (options.outputSrtPath) {
    args.push('--output-srt', resolve(options.outputSrtPath));
  }

  const { stdout } = await execBinary(python, args);

  if (options.outputJsonPath) {
    const raw = await readFile(resolve(options.outputJsonPath), 'utf8');
    return JSON.parse(raw) as WhisperTranscript;
  }

  return JSON.parse(stdout) as WhisperTranscript;
}
