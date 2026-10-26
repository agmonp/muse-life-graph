"""Placeholder score: a gentle synthesized pad + plucked arpeggio, per mood.

Stand-in until MusicGen (Meta open weights) is wired in on Day 6. Seeded per
film so two films don't sound identical, and long enough for any edit.
"""
from __future__ import annotations

import numpy as np

SR = 44100
A4 = 440.0
# (key semitone offset from C, tempo, progression as scale-degree chord roots, minor flags)
MOODS = {
    "warm":    (0, 84, [0, 7, 9, 5], [False, False, True, False]),       # I V vi IV
    "joyful":  (2, 104, [0, 5, 7, 0], [False, False, False, False]),     # I IV V I
    "tender":  (5, 72, [9, 5, 0, 7], [True, False, False, False]),       # vi IV I V
    "playful": (7, 112, [0, 9, 5, 7], [False, True, False, False]),      # I vi IV V
    "epic":    (9, 90, [0, 8, 3, 10], [True, False, False, False]),      # i VI III VII
}


def _freq(semitone_from_c4: float) -> float:
    return A4 * 2 ** ((semitone_from_c4 - 9) / 12)


def _env(n: int, attack: float, release: float) -> np.ndarray:
    e = np.ones(n)
    a, r = int(attack * SR), int(release * SR)
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def score(duration: float, mood: str = "warm", seed: int = 0) -> np.ndarray:
    key, bpm, prog, minor = MOODS.get(mood, MOODS["warm"])
    rng = np.random.default_rng(seed)
    key += int(rng.integers(-2, 3))
    beat = 60 / bpm
    bar = 4 * beat
    total = int((duration + 2) * SR)
    out = np.zeros(total)
    t_bar = 0.0
    i = 0
    while t_bar < duration + 2:
        root = key + prog[i % len(prog)]
        third = 3 if minor[i % len(minor)] else 4
        chord = [root - 12, root, root + third, root + 7, root + 12]
        n = int(2 * bar * SR)
        t = np.arange(n) / SR
        pad = sum(np.sin(2 * np.pi * _freq(s) * t + rng.random()) * (0.5 if s < root else 0.28) for s in chord)
        pad *= (1 + 0.08 * np.sin(2 * np.pi * 0.25 * t)) * _env(n, 0.9, 1.0)
        s0 = int(t_bar * SR)
        seg = out[s0:s0 + n]
        seg += pad[:len(seg)] * 0.10
        # plucked arpeggio on eighth notes over the same two bars
        notes = [root + 12, root + 12 + third, root + 19, root + 24]
        for k in range(16):
            nt = int(k * beat / 2 * SR)
            ln = int(0.9 * SR)
            tt = np.arange(ln) / SR
            f = _freq(notes[(k + i) % len(notes)])
            pluck = (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt)) * np.exp(-tt * 5)
            a = s0 + nt
            if a < total:
                end = min(total, a + ln)
                out[a:end] += pluck[:end - a] * 0.05
        t_bar += 2 * bar
        i += 1
    out = out[:int(duration * SR)]
    out *= _env(len(out), 0.05, min(2.5, duration / 4))
    return (out / (np.abs(out).max() + 1e-9) * 0.6).astype(np.float32)
