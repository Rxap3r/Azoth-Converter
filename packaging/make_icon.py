"""Draw the Azoth Converter app icon. Run from the repository root:

    python packaging/make_icon.py

Design "F1": a document with a golden seal holding two circular arrows, on a deep
indigo tile with a soft glow and two sparkles. Writes packaging/icon.ico (executables
and installer) and src/azoth/resources/icon.png (window and taskbar), plus
packaging/icon_preview.png to check the small sizes.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
S = 1024  # drawn large, then scaled down for crisp small sizes

TILE_TOP = (44, 30, 120)
TILE_BOTTOM = (14, 10, 48)
GLOW = (130, 100, 255)
GOLD = (245, 190, 70)
GOLD_LIGHT = (255, 226, 140)
NIGHT = (40, 26, 100)
PAPER = (250, 246, 236)
FOLD = (220, 210, 190)
LINES = (190, 175, 220)
LILAC = (200, 190, 255)


def tile() -> tuple[Image.Image, Image.Image]:
    grad = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        d.line(
            (0, y, S, y),
            fill=tuple(int(a + (b - a) * t) for a, b in zip(TILE_TOP, TILE_BOTTOM, strict=True)),
        )
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    return img, mask


def glow(img: Image.Image, mask: Image.Image, center, radius: int, color, strength: int) -> None:
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    x, y = center
    ImageDraw.Draw(layer).ellipse(
        (x - radius, y - radius, x + radius, y + radius), fill=(*color, strength)
    )
    layer = layer.filter(ImageFilter.GaussianBlur(radius / 2.2))
    clipped = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    clipped.paste(layer, (0, 0), mask)
    img.alpha_composite(clipped)


def sparkle(d: ImageDraw.ImageDraw, x: float, y: float, r: float, color) -> None:
    k = 0.25
    d.polygon(
        [
            (x, y - r),
            (x + r * k, y - r * k),
            (x + r, y),
            (x + r * k, y + r * k),
            (x, y + r),
            (x - r * k, y + r * k),
            (x - r, y),
            (x - r * k, y - r * k),
        ],
        fill=color,
    )


def document(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    fold = int(w * 0.27)
    d.polygon(
        [(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)], fill=PAPER
    )
    d.polygon([(x + w - fold, y), (x + w - fold, y + fold), (x + w, y + fold)], fill=FOLD)
    for i in range(4):
        ly = y + fold + int(h * 0.11) + i * int(h * 0.13)
        short = int(w * 0.23) if i == 3 else 0
        d.rounded_rectangle(
            (x + int(w * 0.15), ly, x + w - int(w * 0.15) - short, ly + int(h * 0.055)),
            radius=11,
            fill=LINES,
        )


def curved_arrow(d, cx, cy, r, start, end, width, color) -> None:
    """Arc on the centre-line radius r from `start` to `end` degrees (clockwise on screen),
    ending in a symmetric arrowhead that is centred on the line and points along it."""
    head_len, head_w = width * 1.7, width * 2.3
    stop = end - math.degrees(head_len / r)
    outer, inner = [], []
    steps = max(24, int(abs(stop - start)))
    for i in range(steps + 1):
        a = math.radians(start + (stop - start) * i / steps)
        outer.append((cx + (r + width / 2) * math.cos(a), cy + (r + width / 2) * math.sin(a)))
        inner.append((cx + (r - width / 2) * math.cos(a), cy + (r - width / 2) * math.sin(a)))
    d.polygon(outer + inner[::-1], fill=color)
    a0 = math.radians(start)  # round tail
    tx, ty = cx + r * math.cos(a0), cy + r * math.sin(a0)
    d.ellipse((tx - width / 2, ty - width / 2, tx + width / 2, ty + width / 2), fill=color)
    ab = math.radians(stop)
    bx, by = cx + r * math.cos(ab), cy + r * math.sin(ab)
    nx, ny = math.cos(ab), math.sin(ab)  # across the line
    ax, ay = -math.sin(ab), math.cos(ab)  # along the line
    d.polygon(
        [
            (bx + nx * head_w / 2, by + ny * head_w / 2),
            (bx + ax * head_len, by + ay * head_len),
            (bx - nx * head_w / 2, by - ny * head_w / 2),
        ],
        fill=color,
    )


def seal(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    d.ellipse((cx - r - 18, cy - r - 18, cx + r + 18, cy + r + 18), fill=NIGHT)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GOLD)
    inner = r * 0.82
    d.ellipse(
        (cx - inner, cy - inner, cx + inner, cy + inner),
        outline=GOLD_LIGHT,
        width=max(6, int(r * 0.06)),
    )
    ring, width, gap = r * 0.5, r * 0.17, 24
    curved_arrow(d, cx, cy, ring, 180 + gap, 360 - gap, width, NIGHT)
    curved_arrow(d, cx, cy, ring, gap, 180 - gap, width, NIGHT)


def draw() -> Image.Image:
    img, mask = tile()
    glow(img, mask, (512, 512), 330, GLOW, 120)
    d = ImageDraw.Draw(img)
    document(d, 312, 212, 360, 470)
    seal(d, 640, 640, 165)
    sparkle(d, 820, 220, 46, GOLD_LIGHT)
    sparkle(d, 230, 800, 30, LILAC)
    return img


def main() -> None:
    img = draw()
    png = ROOT / "src" / "azoth" / "resources" / "icon.png"
    img.resize((256, 256), Image.Resampling.LANCZOS).save(png, optimize=True)
    ico = ROOT / "packaging" / "icon.ico"
    img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    preview = Image.new("RGBA", (256 + 128 + 64 + 48 + 32 + 16 + 100, 270), (240, 240, 240, 255))
    x = 10
    for size in (256, 128, 64, 48, 32, 16):
        preview.alpha_composite(img.resize((size, size), Image.Resampling.LANCZOS), (x, 260 - size))
        x += size + 15
    preview.save(ROOT / "packaging" / "icon_preview.png")
    print(f"Wrote {png} and {ico}")


if __name__ == "__main__":
    main()
