"""Genera los íconos de la PWA (static/img/icon-*.png) con Pillow. Uso: python scripts/make_icons.py"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "img"
BRAND, GOLD = (86, 26, 36), (212, 175, 55)


def icon(size: int, maskable: bool = False) -> Image.Image:
    img = Image.new("RGB", (size, size), BRAND)
    draw = ImageDraw.Draw(img)
    pad = size * (0.22 if maskable else 0.12)
    # montaña del Valle Sagrado
    draw.polygon(
        [
            (pad, size - pad),
            (size * 0.42, size * 0.38),
            (size * 0.58, size * 0.56),
            (size * 0.7, size * 0.44),
            (size - pad, size - pad),
        ],
        fill=GOLD,
    )
    try:
        font = ImageFont.truetype("arialbd.ttf", int(size * 0.26))
    except OSError:
        font = ImageFont.load_default()
    draw.text((size / 2, size * 0.24 + (pad * 0.3)), "LS", fill="white", font=font, anchor="mm")
    return img


OUT.mkdir(parents=True, exist_ok=True)
for s in (192, 512):
    icon(s).save(OUT / f"icon-{s}.png")
icon(512, maskable=True).save(OUT / "icon-maskable-512.png")
icon(180).save(OUT / "apple-touch-icon.png")
print("Íconos generados en", OUT)
