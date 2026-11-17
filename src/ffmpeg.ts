import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import type { MediaProbeResult } from './types.js';

export interface CommandOutput {
  stdout: string;
  stderr: string;
  exitCode: number;
}

/**
 * Execute an external binary and collect stdout/stderr.
 */
export function execBinary(bin: string, args: string[]): Promise<CommandOutput> {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, { windowsHide: true });
    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (chunk: Buffer) => {
      stdout += chunk.toString('utf8');
    });
    child.stderr.on('data', (chunk: Buffer) => {
      stderr += chunk.toString('utf8');
    });
    child.on('error', (err) => {
      reject(new Error(`Failed to start "${bin}": ${err.message}`));
    });
    child.on('close', (code) => {
      const exitCode = code ?? 1;
      if (exitCode !== 0) {
        reject(new Error(`"${bin}" exited with code ${exitCode}:\n${stderr.trim()}`));
        return;
      }
      resolve({ stdout, stderr, exitCode });
    });
  });
}

/**
 * Verify that ffmpeg and ffprobe are accessible on PATH or at the given paths.
 */
export async function checkFfmpegAvailable(
  ffmpegPath = 'ffmpeg',
  ffprobePath = 'ffprobe',
): Promise<{ ffmpegVersion: string; ffprobeVersion: string }> {
  const [ffOut, fpOut] = await Promise.all([
    execBinary(ffmpegPath, ['-version']),
    execBinary(ffprobePath, ['-version']),
  ]);
  return {
    ffmpegVersion: ffOut.stdout.split(/\r?\n/)[0] ?? '',
    ffprobeVersion: fpOut.stdout.split(/\r?\n/)[0] ?? '',
  };
}

/**
 * Probe a media file using ffprobe and return structured metadata.
 */
export async function probeMedia(
  filePath: string,
  ffprobePath = 'ffprobe',
): Promise<MediaProbeResult> {
  const { stdout } = await execBinary(ffprobePath, [
    '-v',
    'quiet',
    '-print_format',
    'json',
    '-show_format',
    '-show_streams',
    filePath,
  ]);

  const raw = JSON.parse(stdout) as {
    format?: Record<string, string>;
    streams?: Array<Record<string, unknown>>;
  };

  return {
    format: {
      filename: raw.format?.filename,
      duration: raw.format?.duration ? Number(raw.format.duration) : undefined,
      size: raw.format?.size ? Number(raw.format.size) : undefined,
      bitRate: raw.format?.bit_rate ? Number(raw.format.bit_rate) : undefined,
      formatName: raw.format?.format_name,
    },
    streams: (raw.streams ?? []).map((s) => ({
      index: Number(s.index ?? 0),
      codecType: typeof s.codec_type === 'string' ? s.codec_type : undefined,
      codecName: typeof s.codec_name === 'string' ? s.codec_name : undefined,
      width: typeof s.width === 'number' ? s.width : undefined,
      height: typeof s.height === 'number' ? s.height : undefined,
      rFrameRate: typeof s.r_frame_rate === 'string' ? s.r_frame_rate : undefined,
      duration: typeof s.duration === 'string' ? Number(s.duration) : undefined,
    })),
  };
}

/**
 * Escape a filesystem path for FFmpeg filter arguments (handles Windows drive colons).
 */
function escapeFilterPath(filePath: string): string {
  return filePath.replace(/\\/g, '/').replace(/:/g, '\\:');
}

/**
 * Mux a rendered video with an audio track and optional burned-in SRT subtitles.
 */
export async function muxAudioAndSubtitles(options: {
  videoPath: string;
  audioPath: string;
  outputPath: string;
  srtPath?: string;
  ffmpegPath?: string;
}): Promise<string> {
  const outputPath = resolve(options.outputPath);
  await mkdir(dirname(outputPath), { recursive: true });

  const args: string[] = [
    '-y',
    '-i',
    resolve(options.videoPath),
    '-i',
    resolve(options.audioPath),
  ];

  if (options.srtPath) {
    const escapedSrt = escapeFilterPath(resolve(options.srtPath));
    args.push(
      '-vf',
      `subtitles='${escapedSrt}':force_style='FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2'`,
      '-c:v',
      'libx264',
      '-pix_fmt',
      'yuv420p',
    );
  } else {
    args.push('-c:v', 'copy');
  }

  args.push('-c:a', 'aac', '-shortest', '-movflags', '+faststart', outputPath);

  await execBinary(options.ffmpegPath ?? 'ffmpeg', args);
  return outputPath;
}
