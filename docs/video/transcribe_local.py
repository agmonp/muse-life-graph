"""Transcribe the owner's recording locally with an already cached Whisper model.

No audio is uploaded; local_files_only and HF_HUB_OFFLINE prevent model downloads.
API approach: SYSTRAN/faster-whisper, MIT, pinned reference
9e472ae9de8bb374552f531f752654554b76b2d6, README.md:183 (word timestamps).
No source implementation is copied.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default='data/video/owner_raw.mp4')
    ap.add_argument('--out', default='data/video/owner_transcript.json')
    a = ap.parse_args()
    os.environ['HF_HUB_OFFLINE'] = '1'
    from faster_whisper import WhisperModel
    import numpy as np

    cache = Path.home() / '.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots'
    model_path = next(p for p in cache.iterdir() if (p / 'model.bin').exists())
    model = WhisperModel(str(model_path), device='cpu', compute_type='int8', cpu_threads=8,
                         local_files_only=True)
    # Decode with the installed FFmpeg (avoids a PyAV 19 compatibility change).
    decoded = subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', a.src, '-vn',
                              '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'],
                             capture_output=True, check=True)
    samples = np.frombuffer(decoded.stdout, dtype=np.float32)
    segments, info = model.transcribe(samples, language='en', beam_size=5, word_timestamps=True,
                                      vad_filter=True, condition_on_previous_text=False)
    rows = []
    for s in segments:
        row = {'start': s.start, 'end': s.end, 'text': s.text,
               'words': [{'start': w.start, 'end': w.end, 'word': w.word, 'probability': w.probability}
                         for w in s.words or []]}
        rows.append(row)
        print(f'{s.start:.2f}-{s.end:.2f} {s.text}', flush=True)
    Path(a.out).write_text(json.dumps({'language': info.language, 'duration': info.duration,
                                      'model': model_path.name, 'local_only': True, 'segments': rows},
                                     ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
