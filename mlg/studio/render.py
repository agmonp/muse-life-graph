"""Render an EDL to MP4: our own frame loop (PIL + numpy) piped into ffmpeg.

- stills drift (Ken Burns) toward the focus face; in 9:16 the crop is centred on it,
  so a landscape photo becomes a portrait shot without cutting heads off
- clips are decoded at output size and play with their own sound
- frame 0 is the title card (a shared film must never open black)
- captions / subtitles / year labels are drawn once per shot and faded in and out
- audio: score + clip sound + voice lines, music ducked under any speech
"""
from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from mlg.muse.media import open_image
from mlg.perceive.keyframes import keyframes
from mlg.studio import music

FPS = 25
SR = music.SR
FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")]
FONTS = {"bold": ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
         "regular": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]}


def size_for(aspect: str, height: int = 720) -> tuple[int, int]:
    return (height * 16 // 9 // 2 * 2, height) if aspect == "16:9" else (height * 9 // 16 // 2 * 2, height)


@lru_cache(maxsize=32)
def font(weight: str, px: int) -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        for name in FONTS[weight]:
            if (d / name).exists():
                return ImageFont.truetype(str(d / name), px)
    return ImageFont.load_default(px)


def _visual(text: str) -> str:
    """Right-to-left text without a shaping engine: reverse it so Hebrew reads correctly."""
    if any("\u0590" <= c <= "\u05ff" for c in text) and not features.check("raqm"):
        return text[::-1]
    return text


def _wrap(draw: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=f) <= width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def _text_block(layer: Image.Image, text: str, f, center_y: int, max_w: int, shadow: int = 3) -> None:
    d = ImageDraw.Draw(layer)
    lines = _wrap(d, text, f, max_w)
    lh = int(f.size * 1.25)
    y = center_y - lh * len(lines) // 2
    for line in lines:
        vis = _visual(line)
        w = d.textlength(vis, font=f)
        x = (layer.width - w) / 2
        d.text((x + shadow, y + shadow), vis, font=f, fill=(0, 0, 0, 170))
        d.text((x, y), vis, font=f, fill=(255, 255, 255, 255))
        y += lh


def overlay_for(shot: dict, W: int, H: int) -> np.ndarray | None:
    """RGBA overlay (float 0..1) with the shot's title / caption / year / end text."""
    if not any(shot.get(k) for k in ("title", "caption", "year", "text")):
        return None
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    short = min(W, H)
    if shot.get("title"):
        grad = Image.linear_gradient("L").resize((W, H)).point(lambda v: int(v * 0.75))
        shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shade.putalpha(grad)
        layer = Image.alpha_composite(layer, shade)
        _text_block(layer, shot["title"], font("bold", int(short * 0.11)), int(H * 0.77), int(W * 0.86))
        if shot.get("title_sub"):
            _text_block(layer, shot["title_sub"], font("regular", int(short * 0.05)), int(H * 0.88), int(W * 0.86), 2)
    if shot.get("caption"):
        band = Image.new("RGBA", (W, int(H * 0.22)), (0, 0, 0, 0))
        band.putalpha(Image.linear_gradient("L").resize(band.size).point(lambda v: int(v * 0.6)))
        layer.alpha_composite(band, (0, H - band.height))
        _text_block(layer, shot["caption"], font("regular", int(short * 0.055)), int(H * 0.88), int(W * 0.84), 2)
    if shot.get("year"):
        d = ImageDraw.Draw(layer)
        f = font("bold", int(short * 0.06))
        d.text((int(W * 0.045) + 2, int(H * 0.05) + 2), shot["year"], font=f, fill=(0, 0, 0, 150))
        d.text((int(W * 0.045), int(H * 0.05)), shot["year"], font=f, fill=(255, 255, 255, 235))
    if shot.get("kind") == "end":
        dim = Image.new("RGBA", (W, H), (0, 0, 0, 150))
        layer = Image.alpha_composite(dim, layer)
        if shot.get("text"):
            _text_block(layer, shot["text"], font("bold", int(short * 0.085)), H // 2, int(W * 0.84))
    return layer


def _sub_font(W: int, H: int):
    return font("regular", int(min(W, H) * 0.045))


def subtitle_chunks(text: str, a0: float, a1: float, W: int, H: int) -> list[tuple[float, float, str]]:
    """Split a long line into readable 2-line cards, each on screen for its share of the time."""
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = _wrap(d, text, _sub_font(W, H), int(W * 0.84))
    cards = [" ".join(lines[i:i + 2]) for i in range(0, len(lines), 2)] or [text]
    total = sum(len(c) for c in cards)
    out, t = [], a0
    for c in cards:
        dt = (a1 - a0) * len(c) / total
        out.append((t, t + dt, c))
        t += dt
    return out


def subtitle_layer(text: str, W: int, H: int) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    f = _sub_font(W, H)
    d = ImageDraw.Draw(layer)
    lines = _wrap(d, text, f, int(W * 0.84))
    lh = int(f.size * 1.6)
    y = int(H * 0.93) - lh * len(lines)
    for line in lines:
        vis = _visual(line)
        x0, y0, x1, y1 = d.textbbox((0, 0), vis, font=f)
        x = (W - (x1 - x0)) / 2
        d.rounded_rectangle((x - 10, y + y0 - 6, x + (x1 - x0) + 10, y + y1 + 6), 8, fill=(0, 0, 0, 150))
        d.text((x, y), vis, font=f, fill=(255, 255, 255, 255))
        y += lh
    return layer


class Overlay:
    """An RGBA layer split once into colour + alpha, so fading it in is a cheap C-level paste."""

    def __init__(self, layer: Image.Image):
        self.rgb = layer.convert("RGB")
        self.alpha = layer.getchannel("A")
        self._faded: dict[int, Image.Image] = {}

    def paste_on(self, frame: Image.Image, strength: float) -> None:
        level = int(round(max(0.0, min(1.0, strength)) * 20))   # 21 fade steps are smooth at 25 fps
        if level == 0:
            return
        if level not in self._faded:
            self._faded[level] = self.alpha if level == 20 else self.alpha.point(lambda v: v * level // 20)
        frame.paste(self.rgb, (0, 0), self._faded[level])


VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp")


class Still:
    def __init__(self, shot: dict, W: int, H: int, index: int):
        path = Path(shot["path"])
        img = (open_image(keyframes(path)[len(keyframes(path)) // 2][1]) if path.suffix.lower() in VIDEO_EXT
               else open_image(path))
        iw, ih = img.size
        # shrink once to what the deepest zoom needs, so each frame resamples a small image
        scale = min(1.0, W * 1.25 / min(iw, ih * W / H))
        if scale < 1.0:
            img = img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)
        if shot.get("kind") == "end":   # the closing card is a card, not the last picture shown again
            img = img.filter(ImageFilter.GaussianBlur(max(8, min(img.size) // 40)))
        self.img, self.W, self.H, self.dur = img, W, H, shot["dur"]
        iw, ih = img.size
        bw = min(iw, ih * W / H)
        bh = bw * H / W
        fx, fy = iw / 2, ih / 2
        if shot.get("focus"):
            x1, y1, x2, y2 = shot["focus"]
            fx, fy = (x1 + x2) / 2000 * iw, (y1 + (y2 - y1) * 0.3) / 1000 * ih  # upper part = the face
        self.base = (bw, bh)
        self.focus = (fx, fy)
        # alternate zoom in / zoom out so consecutive stills don't feel the same
        self.z0, self.z1 = (1.0, 1.16) if index % 2 == 0 else (1.16, 1.0)

    def frame(self, t: float) -> Image.Image:
        p = min(1.0, max(0.0, t / max(self.dur, 0.01)))
        p = p * p * (3 - 2 * p)
        z = self.z0 + (self.z1 - self.z0) * p
        iw, ih = self.img.size
        w, h = self.base[0] / z, self.base[1] / z
        # start centred on the face for portrait crops, else drift from frame centre to the face
        cx = self.focus[0] if self.H > self.W else iw / 2 + (self.focus[0] - iw / 2) * p * 0.6
        cy = ih / 2 + (self.focus[1] - ih / 2) * (0.35 + 0.65 * p) if self.H <= self.W else self.focus[1]
        x0 = min(max(0, cx - w / 2), iw - w)
        y0 = min(max(0, cy - h / 2), ih - h)
        return self.img.resize((self.W, self.H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h))


class Clip:
    def __init__(self, shot: dict, W: int, H: int):
        self.W, self.H, self.dur = W, H, shot["dur"]
        self.proc = subprocess.Popen(
            [shutil.which("ffmpeg"), "-v", "error", "-ss", f"{shot.get('t0', 0):.2f}", "-i", shot["path"],
             "-t", f"{shot['dur']:.2f}", "-vf",
             f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.last = Image.new("RGB", (W, H))
        self.read = 0

    def frame(self, t: float) -> Image.Image:
        want = int(t * FPS)
        while self.read <= want:
            buf = self.proc.stdout.read(self.W * self.H * 3)
            self.read += 1
            if len(buf) < self.W * self.H * 3:
                break
            self.last = Image.frombytes("RGB", (self.W, self.H), buf)
        return self.last.copy()

    def close(self) -> None:
        self.proc.kill()


def _alpha_at(local: float, dur: float, fade: float = 0.4) -> float:
    return max(0.0, min(1.0, local / fade, (dur - local) / fade))


def render_video(edl: dict, out: Path, height: int = 720) -> Path:
    W, H = size_for(edl["aspect"], height)
    shots, xf = edl["shots"], edl["xfade"]
    total = edl["duration"]
    n_frames = int(total * FPS)
    subs = [(v["at"], v["at"] + v["t1"] - v["t0"], v["text"]) for v in edl["voices"]]
    subs += [(s["start"] + 0.2, s["start"] + s["dur"] - 0.3, s["subtitle"]) for s in shots if s.get("subtitle")]
    subs = [c for a0, a1, txt in subs for c in subtitle_chunks(txt, a0, a1, W, H)]
    sub_layers = {txt: Overlay(subtitle_layer(txt, W, H)) for _, _, txt in subs}
    enc = subprocess.Popen([shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "20", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    live: dict[int, tuple] = {}
    try:
        for fi in range(n_frames):
            t = fi / FPS
            frame = None
            for i, s in enumerate(shots):
                if not (s["start"] <= t < s["start"] + s["dur"]):
                    if i in live and t >= s["start"] + s["dur"]:
                        src = live.pop(i)[0]
                        if isinstance(src, Clip):
                            src.close()
                    continue
                if i not in live:
                    src = Clip(s, W, H) if s["kind"] == "clip" else Still(s, W, H, i)
                    layer = overlay_for(s, W, H)
                    live[i] = (src, Overlay(layer) if layer is not None else None)
                src, ov = live[i]
                local = t - s["start"]
                img = src.frame(local)
                if ov is not None:
                    ov.paste_on(img, 1.0 if s["kind"] == "title" and local < s["dur"] - 0.6
                                else _alpha_at(local, s["dur"]))
                # crossfade: the later shot fades in over the earlier one (first shot: no fade - frame 0 is the title)
                w = 1.0 if i == 0 or local >= xf else local / xf
                frame = img if frame is None or w >= 1.0 else Image.blend(frame, img, w)
            if frame is None:
                frame = Image.new("RGB", (W, H))
            for a0, a1, txt in subs:
                if a0 <= t < a1:
                    sub_layers[txt].paste_on(frame, _alpha_at(t - a0, a1 - a0, 0.25))
            enc.stdin.write(frame.tobytes())
    finally:
        for src, _ in live.values():
            if isinstance(src, Clip):
                src.close()
        enc.stdin.close()
        enc.wait()
    return out


def _pcm(path: str, t0: float, dur: float) -> np.ndarray:
    r = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-ss", f"{t0:.2f}", "-i", path, "-t", f"{dur:.2f}",
                        "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.float32).copy()


def _place(track: np.ndarray, clip: np.ndarray, at: float, fade: float = 0.2) -> None:
    a = int(at * SR)
    n = min(len(clip), len(track) - a)
    if n <= 0:
        return
    c = clip[:n].copy()
    f = min(int(fade * SR), n // 2)
    if f:
        c[:f] *= np.linspace(0, 1, f)
        c[-f:] *= np.linspace(1, 0, f)
    track[a:a + n] += c


def _level(clip: np.ndarray, rms: float = 0.11, max_gain: float = 6.0) -> np.ndarray:
    """Bring every voice source (clip sound, blessing, narrator) to the same loudness."""
    cur = float(np.sqrt(np.mean(clip ** 2))) if len(clip) else 0.0
    return clip * min(max_gain, rms / cur) if cur > 1e-4 else clip


def render_audio(edl: dict, out: Path, seed: int = 0) -> Path:
    from mlg.studio.edit import NARRATION_LEAD
    total = edl["duration"]
    n = int(total * SR)
    speech = np.zeros(n, np.float32)
    for s in edl["shots"]:
        if s["kind"] == "clip" and s.get("own_audio"):
            _place(speech, _level(_pcm(s["path"], s.get("t0", 0), s["dur"])), s["start"])
        if s.get("narration"):
            _place(speech, _level(_pcm(s["narration"]["path"], 0, s["narration"]["dur"] + 0.1), 0.1),
                   s["start"] + NARRATION_LEAD, fade=0.05)
    for v in edl["voices"]:
        _place(speech, _level(_pcm(v["path"], v["t0"], v["t1"] - v["t0"] + 0.3)), v["at"])
    # duck the music wherever someone speaks (smoothed envelope)
    active = (np.abs(speech) > 0.01).astype(np.float64)
    k = int(0.4 * SR)
    # centred moving average via a cumulative sum: O(n), where np.convolve was O(n*k) (minutes)
    c = np.concatenate([[0.0], np.cumsum(active)])
    lo = np.clip(np.arange(n) - k // 2, 0, n)
    hi = np.clip(np.arange(n) + k // 2, 0, n)
    env = ((c[hi] - c[lo]) / k).astype(np.float32)
    gain = 1.0 - 0.78 * np.clip(env * 4, 0, 1)
    if edl.get("score_path") and Path(edl["score_path"]).exists():
        # MusicGen score: level it, fade out over the closing card
        score = _level(_pcm(edl["score_path"], 0, total + 0.5), 0.09, 3.0)[:n]
        f = min(int(2.5 * SR), len(score) // 3)
        if f:
            score[-f:] *= np.linspace(1, 0, f)
        score_gain = 1.0
    else:
        score = music.score(total, edl.get("music_mood", "warm"), seed)[:n]
        score_gain = 0.5
    mix = np.zeros(n, np.float32)
    mix[:len(score)] += score * score_gain * gain[:len(score)]
    mix += speech
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    sf.write(out, mix, SR)
    return out


def render(edl: dict, out_dir: Path, height: int = 720, seed: int = 0) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    video = render_video(edl, out_dir / "video_only.mp4", height)
    audio = render_audio(edl, out_dir / "mix.wav", seed)
    final = out_dir / "film.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error", "-i", str(video), "-i", str(audio),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
                    str(final)], check=True)
    video.unlink(missing_ok=True)
    return final
