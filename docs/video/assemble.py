"""Cut the demo track of the 3-minute video from the screen captures and film clips; render a draft MP4.

    .venv\\Scripts\\python.exe docs\\video\\assemble.py [--beats docs/video/beats.json] [--out data/video/draft.mp4]

beats.json is the timeline (see SCRIPT.md): each beat is either
  {"screen": "<capture or clip file>", "in": 0.0, "dur": 8.0, "caption": "...", "sound": "film" | "bed" | "none",
   "crop": "w:h:x:y" (optional zoom into the capture)}
or an on-camera gap
  {"camera": "<the line you say>", "dur": 15.0}
Screen beats are scaled to 1920x1080 at 30 fps and get a caption (lower third); camera beats are black with the
line in small grey type, so the draft reads like the final cut and you can record to the gap lengths. Sound:
"film" keeps the clip's own audio (the film's music and voices), "bed" lays the film's score under the beat at
a low level, "none" is silence. Paths in beats.json are relative to the folder `--media` (default data/video).
Needs ffmpeg on PATH. Nothing here is uploaded anywhere.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FONT = "C\\:/Windows/Fonts/segoeui.ttf"
FONT_B = "C\\:/Windows/Fonts/segoeuib.ttf"
W, H, FPS = 1920, 1080, 30


def esc(t: str) -> str:
    """Text for ffmpeg drawtext: escape the characters its filter parser treats specially."""
    return (t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")
            .replace(",", "\\,"))


def run(cmd: list[str]) -> None:
    subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error", *cmd], check=True)


def caption_filter(text: str | None, dur: float) -> str:
    if not text:
        return ""
    fade = f"alpha='if(lt(t,0.4),t/0.4,if(gt(t,{dur - 0.4:.2f}),({dur:.2f}-t)/0.4,1))'"
    return (f",drawbox=x=0:y=ih-150:w=iw:h=150:color=black@0.45:t=fill:enable='gte(t,0.2)',"
            f"drawtext=fontfile='{FONT_B}':text='{esc(text)}':fontsize=40:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-102:{fade}")


def screen(beat: dict, media: Path, bed: Path | None, out: Path) -> None:
    src = media / beat["screen"]
    dur = float(beat["dur"])
    crop = f"crop={beat['crop']}," if beat.get("crop") else ""      # "w:h:x:y" of the 1920x1080 capture: a zoom
    vf = (f"{crop}scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
          f"fps={FPS},format=yuv420p" + caption_filter(beat.get("caption"), dur))
    is_image = src.suffix.lower() in (".png", ".jpg", ".jpeg")
    inp = (["-loop", "1", "-t", f"{dur}", "-i", str(src)] if is_image
           else ["-ss", f"{beat.get('in', 0)}", "-t", f"{dur}", "-i", str(src)])
    sound = beat.get("sound", "bed")
    if sound == "film" and not is_image:
        run([*inp, "-vf", vf, "-af", f"apad,atrim=0:{dur},afade=t=out:st={max(0, dur - 0.5)}:d=0.5",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-ar", "48000", "-ac", "2",
             "-t", f"{dur}", str(out)])
    elif sound == "bed" and bed:
        run([*inp, "-ss", f"{beat.get('bed_in', 0)}", "-t", f"{dur}", "-i", str(bed), "-map", "0:v", "-map", "1:a",
             "-vf", vf, "-af", f"volume=0.25,apad,atrim=0:{dur},afade=t=in:d=0.6,afade=t=out:st={max(0, dur - 0.6)}:d=0.6",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-ar", "48000", "-ac", "2",
             "-t", f"{dur}", str(out)])
    else:
        run([*inp, "-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a",
             "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-t", f"{dur}", str(out)])


def camera(beat: dict, out: Path) -> None:
    dur = float(beat["dur"])
    line = beat["camera"]
    words, rows, cur = line.split(), [], ""
    for w in words:   # wrap at ~70 characters
        if len(cur) + len(w) > 70:
            rows.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    rows.append(cur)
    draws = [f"drawtext=fontfile='{FONT_B}':text='ON CAMERA  {dur:.0f} s':fontsize=30:fontcolor=0x9a9a9a:"
             f"x=(w-text_w)/2:y=h/2-{40 + 26 * len(rows)}"]
    draws += [f"drawtext=fontfile='{FONT}':text='{esc(r)}':fontsize=34:fontcolor=0x707070:"
              f"x=(w-text_w)/2:y=h/2-{26 * len(rows) - 10}+{i * 52}" for i, r in enumerate(rows)]
    run(["-f", "lavfi", "-t", f"{dur}", "-i", f"color=c=black:s={W}x{H}:r={FPS}",
         "-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", ",".join(draws) + ",format=yuv420p", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-t", f"{dur}",
         str(out)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--beats", default=str(Path(__file__).with_name("beats.json")))
    ap.add_argument("--media", default=str(ROOT / "data" / "video"))
    ap.add_argument("--out", default=str(ROOT / "data" / "video" / "draft.mp4"))
    a = ap.parse_args()
    spec = json.loads(Path(a.beats).read_text(encoding="utf-8"))
    media = Path(a.media)
    bed = media / spec["bed"] if spec.get("bed") else None
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        t = 0.0
        for i, beat in enumerate(spec["beats"]):
            part = Path(tmp) / f"{i:03d}.mp4"
            if "camera" in beat:
                camera(beat, part)
            else:
                screen(beat, media, bed, part)
            parts.append(part)
            print(f"{t:6.1f}s  {'camera' if 'camera' in beat else beat['screen']:<40} {beat['dur']}s", flush=True)
            t += float(beat["dur"])
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(a.out)])
    print(f"wrote {a.out} ({t:.1f} s)")


if __name__ == "__main__":
    main()
