"""The Meta tools card for the demo video (1920x1080).

    python docs/video/stack_card.py      # -> data/video/stack_card.png
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[2] / "data" / "video" / "stack_card.png"
W, H = 1920, 1080
ROWS = [("Muse Spark 1.3 · 1.2", "perceives every photo, video and voice note"),
        ("Muse Spark Open · Baseten", "search, titles, circles, Picture Checker — open weights"),
        ("Muse Wonder", "writes the film, watches the draft, blind-tests the re-cut"),
        ("Muse Voice Transcribe", "Hebrew and English speech, speaker turns"),
        ("MusicGen · SeamlessM4T", "score and narrator, open weights on a home GPU")]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)


def main() -> None:
    im = Image.new("RGB", (W, H), (24, 20, 18))
    d = ImageDraw.Draw(im)
    d.text((W // 2, 170), "Built on Meta", font=font("segoeuib.ttf", 64), fill=(255, 255, 255), anchor="mm")
    y = 300
    for a, b in ROWS:
        d.text((W // 2 - 40, y), a, font=font("segoeuib.ttf", 42), fill=(242, 140, 90), anchor="rm")
        d.text((W // 2, y), b, font=font("segoeui.ttf", 38), fill=(225, 218, 210), anchor="lm")
        y += 92
    d.text((W // 2, 830), "Built during the hackathon  ·  started October 26, 2026",
           font=font("segoeui.ttf", 40), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, 905), "github.com/agmonp/muse-life-graph", font=font("segoeuib.ttf", 40), fill=(242, 140, 90),
           anchor="mm")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT)


if __name__ == "__main__":
    main()
