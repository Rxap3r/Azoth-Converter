"""Draw the app icon. Run from the repository root:  python packaging/make_icon.py

Writes packaging/icon.ico (Windows executable and installer) and
src/azoth/resources/icon.png (window and taskbar icon).
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
S = 1024  # drawn large, then scaled down for crisp small sizes

BLUE_TOP = (52, 120, 246)
BLUE_BOTTOM = (28, 70, 180)
SHEET_BACK = (205, 222, 255)
SHEET_FRONT = (255, 255, 255)
FOLD = (220, 230, 248)
LINES = (176, 196, 232)
ARROW = (255, 176, 46)


def rounded_gradient_tile() -> Image.Image:
    grad = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        d.line(
            (0, y, S, y),
            fill=tuple(int(a + (b - a) * t) for a, b in zip(BLUE_TOP, BLUE_BOTTOM, strict=True)),
        )
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=255)
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile.paste(grad, (0, 0), mask)
    return tile


def sheet(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, fill, lines: bool) -> None:
    fold = w // 4
    d.polygon(
        [(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)],
        fill=fill,
    )
    d.polygon([(x + w - fold, y), (x + w - fold, y + fold), (x + w, y + fold)], fill=FOLD)
    if lines:
        for i in range(4):
            ly = y + fold + 70 + i * 62
            d.rounded_rectangle(
                (x + 55, ly, x + w - 55 - (90 if i == 3 else 0), ly + 26), radius=13, fill=LINES
            )


def arrow_badge(img: Image.Image) -> None:
    """Two curved arrows in a circle: 'convert'."""
    d = ImageDraw.Draw(img)
    cx, cy, r = 690, 690, 215
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255))
    ring = 118
    w = 46
    d.arc((cx - ring, cy - ring, cx + ring, cy + ring), 200, 340, fill=ARROW, width=w)
    d.arc((cx - ring, cy - ring, cx + ring, cy + ring), 20, 160, fill=ARROW, width=w)
    # arrow heads at the end of each arc
    for angle, direction in ((340, 1), (160, 1)):
        import math

        a = math.radians(angle)
        px, py = cx + ring * math.cos(a), cy + ring * math.sin(a)
        tx, ty = -math.sin(a) * direction, math.cos(a) * direction  # tangent
        nx, ny = math.cos(a), math.sin(a)  # normal
        size = 62
        tip = (px + tx * size, py + ty * size)
        left = (px + nx * size * 0.9, py + ny * size * 0.9)
        right = (px - nx * size * 0.9, py - ny * size * 0.9)
        d.polygon([tip, left, right], fill=ARROW)


def main() -> None:
    img = rounded_gradient_tile()
    d = ImageDraw.Draw(img)
    sheet(d, 250, 170, 380, 500, SHEET_BACK, lines=False)
    sheet(d, 190, 250, 400, 530, SHEET_FRONT, lines=True)
    arrow_badge(img)

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
