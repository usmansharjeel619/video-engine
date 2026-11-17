import { copyFile, mkdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { muxAudioAndSubtitles } from './ffmpeg.js';
import { renderHyperframes } from './hyperframes.js';
import { synthesizeSpeech } from './tts.js';
import type { PipelineOptions, WhisperTranscript } from './types.js';
import { transcribeWithWhisper } from './whisper.js';

export interface PipelineResult {
  outputPath: string;
  audioPath: string;
  srtPath: string;
  transcript: WhisperTranscript;
}

/**
 * Full end-to-end video pipeline:
 * 1. Synthesize narration audio via Edge TTS
 * 2. Transcribe word-level timestamps & SRT via Whisper (faster-whisper)
 * 3. Render HTML/GSAP composition via Hyperframes
 * 4. Mux audio (and optional burned-in subtitles) via FFmpeg
 */
export async function runVideoPipeline(options: PipelineOptions): Promise<PipelineResult> {
  const compositionDir = resolve(options.compositionDir);
  const outputPath = resolve(options.outputPath);
  const workDir = resolve(options.workDir ?? join(dirname(outputPath), '.work'));
  await mkdir(workDir, { recursive: true });

  const audioPath = join(workDir, 'narration.mp3');
  const ttsTimingsPath = join(workDir, 'tts-timings.json');
  const transcriptJsonPath = join(workDir, 'transcript.json');
  const srtPath = join(workDir, 'captions.srt');
  const rawVideoPath = join(workDir, 'hyperframes-raw.mp4');

  // 1. Edge TTS
  await synthesizeSpeech({
    text: options.narrationText,
    outputPath: audioPath,
    voice: options.voice,
    timingsPath: ttsTimingsPath,
  });

  // 2. Whisper transcription
  const transcript = await transcribeWithWhisper({
    inputPath: audioPath,
    model: options.whisperModel ?? 'base',
    outputJsonPath: transcriptJsonPath,
    outputSrtPath: srtPath,
  });

  // Stage transcript + audio inside compositionDir/assets for Hyperframes compositions that read them
  const assetsDir = join(compositionDir, 'assets');
  await mkdir(assetsDir, { recursive: true });
  await copyFile(audioPath, join(assetsDir, 'narration.mp3'));
  await copyFile(transcriptJsonPath, join(assetsDir, 'transcript.json'));

  // 3. Hyperframes render
  await renderHyperframes({
    projectDir: compositionDir,
    outputPath: rawVideoPath,
    format: 'mp4',
  });

  // 4. FFmpeg mux audio + optional subtitles
  await muxAudioAndSubtitles({
    videoPath: rawVideoPath,
    audioPath,
    outputPath,
    srtPath: options.burnSubtitles ? srtPath : undefined,
  });

  return {
    outputPath,
    audioPath,
    srtPath,
    transcript,
  };
}
