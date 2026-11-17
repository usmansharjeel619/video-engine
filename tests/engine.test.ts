import { mkdtemp, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  checkFfmpegAvailable,
  probeMedia,
  synthesizeSpeech,
  transcribeWithWhisper,
} from '../src/index.js';

describe('Video Engine Toolchain', () => {
  it('verifies FFmpeg and FFprobe are available', async () => {
    const info = await checkFfmpegAvailable();
    expect(info.ffmpegVersion).toMatch(/ffmpeg version/i);
    expect(info.ffprobeVersion).toMatch(/ffprobe version/i);
  });

  it('synthesizes speech with Edge TTS and transcribes it with Whisper', async () => {
    const workDir = await mkdtemp(join(tmpdir(), 'video-engine-e2e-'));
    try {
      const audioPath = join(workDir, 'test.mp3');
      const timingsPath = join(workDir, 'timings.json');
      const srtPath = join(workDir, 'captions.srt');
      const jsonPath = join(workDir, 'transcript.json');

      await synthesizeSpeech({
        text: 'Video engine ready.',
        outputPath: audioPath,
        timingsPath,
      });

      const audioStat = await stat(audioPath);
      expect(audioStat.size).toBeGreaterThan(1000);

      const probe = await probeMedia(audioPath);
      expect(probe.format.duration).toBeGreaterThan(0.5);

      const transcript = await transcribeWithWhisper({
        inputPath: audioPath,
        model: 'tiny',
        outputJsonPath: jsonPath,
        outputSrtPath: srtPath,
      });

      expect(transcript.segments.length).toBeGreaterThan(0);
      expect(transcript.segments[0].text.toLowerCase()).toContain('video');
    } finally {
      await rm(workDir, { recursive: true, force: true });
    }
  }, 60_000);
});
