"""The Dielify icon ("Wave D", picked by Josh 10 Nov 2026): a D made of sound bars.

One shape for everything: drawn here on Android's 108-unit adaptive-icon canvas (launchers
show the middle 72; the safe zone is a circle of 33 round the centre). tools/make_brand.py
turns it into the phone's vector drawables, the PC side-bar logo and the installer images;
icon_image() draws it for the tray and the .exe icon.
"""
from __future__ import annotations

import math

BG_TOP = "#1D1824"     # tile, top-left
BG_BOTTOM = "#0E0F12"  # tile, bottom-right (= the apps' background)
BAR_STOPS = ((0.0, "#FFB35B"), (0.5, "#FF5A5F"), (1.0, "#B84DFF"))  # bars, top to bottom

STEM_H = 46.0     # height of the straight side
RADIUS = STEM_H / 2  # the round side is a half circle
BAR_W = 3.2
STEP = 4.8
STRAIGHT = 3      # full-height bars
CURVED = 5        # bars that follow the curve
LAST_DX = 21.5    # how far the last bar is from the curve's centre (just inside RADIUS)


def bars() -> list[tuple[float, float, float, float]]:
    """(x, y, width, height) of each bar, centred on the 108 canvas."""
    raw = [STEM_H] * STRAIGHT
    for k in range(CURVED - 1, -1, -1):
        dx = LAST_DX - STEP * k
        raw.append(2 * math.sqrt(max(0.0, RADIUS ** 2 - dx ** 2)))
    width = STEP * (len(raw) - 1) + BAR_W
    left = 54 - width / 2
    return [(round(left + i * STEP, 2), round(54 - h / 2, 2), BAR_W, round(h, 2)) for i, h in enumerate(raw)]


BAR_TOP = 54 - STEM_H / 2
BAR_BOTTOM = 54 + STEM_H / 2


def svg(size: int = 108, tile: bool = True, rounded: float = 17) -> str:
    """The icon as SVG. tile=False: bars only, on a transparent background (side-bar logo)."""
    stops = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in BAR_STOPS)
    rects = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{w / 2}" fill="url(#dlb)"/>'
                    for x, y, w, h in bars())
    back = (f'<rect x="18" y="18" width="72" height="72" rx="{rounded}" fill="url(#dlg)"/>' if tile else "")
    view = "18 18 72 72" if tile else "28 28 52 52"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="{view}">'
            f'<defs><linearGradient id="dlg" gradientUnits="userSpaceOnUse" x1="18" y1="18" x2="90" y2="90">'
            f'<stop offset="0" stop-color="{BG_TOP}"/><stop offset="1" stop-color="{BG_BOTTOM}"/></linearGradient>'
            f'<linearGradient id="dlb" gradientUnits="userSpaceOnUse" x1="54" y1="{BAR_TOP}" x2="54" y2="{BAR_BOTTOM}">'
            f'{stops}</linearGradient></defs>{back}{rects}</svg>')


def _rgb(hex_: str) -> tuple[int, int, int]:
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def _mix(stops, t: float) -> tuple[int, int, int]:
    for (o1, c1), (o2, c2) in zip(stops, stops[1:]):
        if t <= o2:
            f = (t - o1) / (o2 - o1) if o2 > o1 else 0
            a, b = _rgb(c1), _rgb(c2)
            return tuple(round(a[i] + (b[i] - a[i]) * f) for i in range(3))
    return _rgb(stops[-1][1])


def icon_image(size: int = 256, tile: bool = True, margin: float = 0.0):
    """The icon as a Pillow RGBA image (drawn 4x larger, then scaled down for smooth edges).

    margin: empty space round the tile, as a share of the size (0 = the tile fills it)."""
    from PIL import Image, ImageDraw

    big = size * 4
    span = 72 if tile else 52
    origin = 18 if tile else 28
    inner = big * (1 - 2 * margin)
    k = inner / span
    off = big * margin

    def p(v: float) -> float:
        return off + (v - origin) * k

    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    if tile:
        bg = Image.new("RGBA", (big, big))
        a, b = _rgb(BG_TOP), _rgb(BG_BOTTOM)
        px = bg.load()
        for yy in range(big):
            for xx in range(0, big, 1):
                t = min(1.0, max(0.0, (xx + yy) / (2 * big)))
                px[xx, yy] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle((p(18), p(18), p(90), p(90)), radius=17 * k, fill=255)
        img.paste(bg, (0, 0), mask)
    grad = Image.new("RGBA", (big, big))
    gd = ImageDraw.Draw(grad)
    top, bottom = p(BAR_TOP), p(BAR_BOTTOM)
    for yy in range(big):
        t = min(1.0, max(0.0, (yy - top) / (bottom - top)))
        gd.line([(0, yy), (big, yy)], fill=_mix(BAR_STOPS, t) + (255,))
    mask = Image.new("L", (big, big), 0)
    md = ImageDraw.Draw(mask)
    for x, y, w, h in bars():
        md.rounded_rectangle((p(x), p(y), p(x + w), p(y + h)), radius=w / 2 * k, fill=255)
    img.paste(grad, (0, 0), mask)
    return img.resize((size, size), Image.LANCZOS)
