#!/usr/bin/env node
import { resolve } from 'node:path';
import { checkFfmpegAvailable, execBinary, probeMedia } from './ffmpeg.js';
import { renderHyperframes } from './hyperframes.js';
import { runVideoPipeline } from './pipeline.js';
import { synthesizeSpeech } from './tts.js';
import { transcribeWithWhisper } from './whisper.js';

function getArg(args: string[], flag: string): string | undefined {
  const idx = args.indexOf(flag);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : undefined;
}

function printUsage(): void {
  console.log(`video-engine CLI (Hyperframes + FFmpeg + Whisper + Edge TTS)

Usage:
  video-engine doctor                                  Check FFmpeg, Python, edge-tts, faster-whisper
  video-engine tts --text "..." -o out.mp3             Synthesize speech with Edge TTS
  video-engine transcribe -i audio.mp3 [--srt out.srt] Transcribe audio/video with Whisper
  video-engine render <compositionDir> -o out.mp4      Render a Hyperframes composition
  video-engine pipeline --text "..." -c <dir> -o out.mp4  Run Edge TTS -> Whisper -> Hyperframes -> FFmpeg
  video-engine probe <media-file>                      Inspect media file metadata
`);
}

async function main(): Promise<void> {
  const [, , command, ...rest] = process.argv;

  if (!command || command === '--help' || command === '-h') {
    printUsage();
    return;
  }

  if (command === 'doctor') {
    const ff = await checkFfmpegAvailable();
    console.log('FFmpeg:', ff.ffmpegVersion);
    console.log('FFprobe:', ff.ffprobeVersion);
    const pyCheck = await execBinary('python', [
      '-c',
      'import edge_tts, faster_whisper; print("edge_tts", edge_tts.__version__ if hasattr(edge_tts, "__version__") else "ok", "| faster_whisper", faster_whisper.__version__)',
    ]);
    console.log('Python:', pyCheck.stdout.trim());
    return;
  }

  if (command === 'probe') {
    const target = rest[0];
    if (!target) throw new Error('Missing <media-file> argument.');
    const result = await probeMedia(resolve(target));
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  if (command === 'tts') {
    const text = getArg(rest, '--text');
    const out = getArg(rest, '-o') ?? 'output/voiceover.mp3';
    const voice = getArg(rest, '--voice');
    const timings = getArg(rest, '--timings');
    if (!text) throw new Error('Missing --text "..." argument.');
    const res = await synthesizeSpeech({ text, outputPath: out, voice, timingsPath: timings });
    console.log(`TTS audio saved: ${res.audioPath}`);
    return;
  }

  if (command === 'transcribe') {
    const input = getArg(rest, '-i');
    if (!input) throw new Error('Missing -i <media-file> argument.');
    const model = getArg(rest, '--model');
    const outJson = getArg(rest, '--json');
    const outSrt = getArg(rest, '--srt');
    const transcript = await transcribeWithWhisper({
      inputPath: input,
      model,
      outputJsonPath: outJson,
      outputSrtPath: outSrt,
    });
    console.log(`Transcribed (${transcript.language}, ${transcript.duration}s, ${transcript.segments.length} segments)`);
    return;
  }

  if (command === 'render') {
    const dir = rest[0] ?? 'composition';
    const out = getArg(rest, '-o') ?? 'output/render.mp4';
    const rendered = await renderHyperframes({ projectDir: dir, outputPath: out });
    console.log(`Rendered: ${rendered}`);
    return;
  }

  if (command === 'pipeline') {
    const text = getArg(rest, '--text');
    if (!text) throw new Error('Missing --text "..." argument.');
    const compositionDir = getArg(rest, '-c') ?? 'composition';
    const outputPath = getArg(rest, '-o') ?? 'output/final.mp4';
    const voice = getArg(rest, '--voice');
    const burnSubtitles = rest.includes('--burn-subtitles');
    const result = await runVideoPipeline({
      narrationText: text,
      compositionDir,
      outputPath,
      voice,
      burnSubtitles,
    });
    console.log(`Pipeline complete: ${result.outputPath}`);
    console.log(`Captions SRT: ${result.srtPath}`);
    return;
  }

  throw new Error(`Unknown command: ${command}`);
}

main().catch((err: unknown) => {
  const message = err instanceof Error ? err.message : String(err);
  console.error(`Error: ${message}`);
  process.exit(1);
});
