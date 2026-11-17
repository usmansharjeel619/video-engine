import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execBinary } from './ffmpeg.js';
import type { HyperframesRenderOptions } from './types.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const HYPERFRAMES_BIN = resolve(__dirname, '..', 'node_modules', 'hyperframes', 'bin', 'hyperframes.mjs');

/**
 * Render an HTML/GSAP composition using Hyperframes.
 */
export async function renderHyperframes(options: HyperframesRenderOptions): Promise<string> {
  const projectDir = resolve(options.projectDir);
  const outputPath = resolve(options.outputPath);
  await mkdir(dirname(outputPath), { recursive: true });

  const args: string[] = [
    HYPERFRAMES_BIN,
    'render',
    projectDir,
    '-o',
    outputPath,
    '--format',
    options.format ?? 'mp4',
  ];

  if (options.fps !== undefined) {
    args.push('--fps', String(options.fps));
  }
  if (options.quality) {
    args.push('--quality', options.quality);
  }
  if (options.framesCacheDir) {
    args.push('--frames-cache-dir', resolve(options.framesCacheDir));
  }

  await execBinary(process.execPath, args);
  return outputPath;
}

/**
 * Run Hyperframes static + runtime validation checks on a composition directory.
 */
export async function checkHyperframes(projectDir: string): Promise<string> {
  const { stdout } = await execBinary(process.execPath, [
    HYPERFRAMES_BIN,
    'check',
    resolve(projectDir),
  ]);
  return stdout;
}
