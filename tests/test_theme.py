"""The light and dark look: readable colours (WCAG contrast) and a complete stylesheet."""

import pytest

pytest.importorskip("PySide6")

from azoth.gui import icons, theme  # noqa: E402


def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("c", [theme.LIGHT_COLORS, theme.DARK_COLORS], ids=["light", "dark"])
def test_text_is_readable(c):
    for background in (c.window, c.content, c.surface, c.note, c.hover):
        assert contrast(c.text, background) >= 7, background
        assert contrast(c.muted, background) >= 4.5, background
    assert contrast(c.accent_text, c.accent) >= 4.5  # Convert button
    assert contrast(c.accent, c.surface) >= 4.5  # links and the selected tile's border
    assert contrast(c.accent_soft_text, c.accent_soft) >= 4.5
    assert contrast(c.success, c.surface) >= 4.5
    assert contrast(c.error, c.surface) >= 4.5
    assert contrast(c.warn_text, c.warn_bg) >= 4.5
    assert contrast(c.libreoffice_text, c.libreoffice_bg) >= 4.5
    assert contrast(c.clean_text, c.clean_bg) >= 4.5
    for category in (*theme.CATEGORIES, "unknown"):
        bg, fg = c.badges[category]
        assert contrast(fg, bg) >= 4.5, category


@pytest.mark.parametrize("c", [theme.LIGHT_COLORS, theme.DARK_COLORS], ids=["light", "dark"])
def test_stylesheet_is_complete(c):
    sheet = theme.stylesheet(c)
    assert "{c." not in sheet and "None" not in sheet
    assert sheet.count("{") == sheet.count("}")
    for category in theme.CATEGORIES:
        assert f'[category="{category}"]' in sheet
    check = sheet.split('image: url("')[1].split('")')[0]
    from pathlib import Path

    assert Path(check).is_file()  # the tick inside a ticked box


def test_icons_render(qapp):
    for name in icons.NAMES:
        pm = icons.pixmap(name, "#3F43C9", 18)
        assert not pm.isNull()
        image = pm.toImage()
        drawn = any(
            image.pixelColor(x, y).alpha() > 0
            for x in range(image.width())
            for y in range(image.height())
        )
        assert drawn, name
        assert pm.deviceIndependentSize().width() == 18
