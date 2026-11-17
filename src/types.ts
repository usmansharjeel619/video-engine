export interface TtsOptions {
  text: string;
  outputPath: string;
  voice?: string;
  rate?: string;
  pitch?: string;
  timingsPath?: string;
  pythonPath?: string;
}

export interface TtsResult {
  audioPath: string;
  timingsPath?: string;
}

export interface WhisperOptions {
  inputPath: string;
  model?: string;
  language?: string;
  device?: 'auto' | 'cpu' | 'cuda';
  computeType?: 'int8' | 'float16' | 'float32';
  outputJsonPath?: string;
  outputSrtPath?: string;
  pythonPath?: string;
}

export interface WhisperWord {
  word: string;
  start: number;
  end: number;
  probability: number;
}

export interface WhisperSegment {
  id: number;
  start: number;
  end: number;
  text: string;
  words: WhisperWord[];
}

export interface WhisperTranscript {
  language: string;
  languageProbability: number;
  duration: number;
  segments: WhisperSegment[];
}

export interface HyperframesRenderOptions {
  projectDir: string;
  outputPath: string;
  format?: 'mp4' | 'webm' | 'mov' | 'gif';
  fps?: number;
  quality?: string;
  framesCacheDir?: string;
}

export interface PipelineOptions {
  narrationText: string;
  compositionDir: string;
  outputPath: string;
  workDir?: string;
  voice?: string;
  whisperModel?: string;
  burnSubtitles?: boolean;
}

export interface MediaProbeResult {
  format: {
    filename?: string;
    duration?: number;
    size?: number;
    bitRate?: number;
    formatName?: string;
  };
  streams: Array<{
    index: number;
    codecType?: string;
    codecName?: string;
    width?: number;
    height?: number;
    rFrameRate?: string;
    duration?: number;
  }>;
}
