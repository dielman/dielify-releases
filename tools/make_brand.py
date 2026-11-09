"""Writes every icon file from the one shape in dielify.brand ("Wave D").

python tools/make_brand.py
  android: res/drawable/ic_launcher_{background,foreground,monochrome}.xml
  PC:      src/dielify/ui/logo.svg (side bar + window favicon)
  setup:   packaging/wizard-{large,small}-{100,200}.bmp (installer pictures)
  TV:      res/drawable-xhdpi/tv_banner.png (the Google TV launcher's 320x180 dp banner)
  docs:    docs/design/brand/icon.png
(packaging/build.py makes dielify.ico itself, from dielify.brand.icon_image.)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from dielify import brand  # noqa: E402

RES = ROOT / "android/app/src/main/res"
FONT = ROOT / "android/app/src/main/res/font/inter_800.ttf"
HEAD = ('<?xml version="1.0" encoding="utf-8"?>\n<!-- Made by tools/make_brand.py from dielify.brand '
        '(the Wave D icon). Don\'t edit by hand. -->\n')


def bar_path() -> str:
    parts = []
    for x, y, w, h in brand.bars():
        r = w / 2
        parts.append(f"M{x:g},{y + r:g} a{r:g},{r:g} 0 0 1 {w:g},0 v{h - w:g} a{r:g},{r:g} 0 0 1 {-w:g},0 Z")
    return " ".join(parts)


def gradient(x1, y1, x2, y2, stops) -> str:
    items = "".join(f'\n                <item android:offset="{o}" android:color="#FF{c[1:]}"/>' for o, c in stops)
    return (f'\n        <aapt:attr name="android:fillColor">\n            <gradient android:type="linear"'
            f' android:startX="{x1}" android:startY="{y1}" android:endX="{x2}" android:endY="{y2}">{items}'
            f'\n            </gradient>\n        </aapt:attr>\n    ')


def vector(body: str) -> str:
    return (HEAD + '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
            '    xmlns:aapt="http://schemas.android.com/aapt"\n'
            '    android:width="108dp" android:height="108dp"\n'
            '    android:viewportWidth="108" android:viewportHeight="108">\n' + body + '</vector>\n')


def android() -> None:
    d = RES / "drawable"
    (d / "ic_launcher_background.xml").write_text(vector(
        '    <path android:pathData="M0,0 H108 V108 H0 Z">'
        + gradient(18, 18, 90, 90, ((0, brand.BG_TOP), (1, brand.BG_BOTTOM))) + '</path>\n'), encoding="utf-8")
    (d / "ic_launcher_foreground.xml").write_text(vector(
        f'    <path android:pathData="{bar_path()}">'
        + gradient(54, brand.BAR_TOP, 54, brand.BAR_BOTTOM, brand.BAR_STOPS) + '</path>\n'), encoding="utf-8")
    (d / "ic_launcher_monochrome.xml").write_text(vector(
        f'    <path android:fillColor="#FFFFFFFF" android:pathData="{bar_path()}"/>\n'), encoding="utf-8")


def wizard(w: int, h: int, scale: int, out: Path, word: bool) -> None:
    img = Image.new("RGB", (w * scale, h * scale), brand.BG_BOTTOM)
    if word:  # tall picture on the installer's first/last page: icon + name, low on a soft glow
        glow = Image.new("RGB", img.size, brand.BG_TOP)
        mask = Image.linear_gradient("L").resize(img.size)
        img = Image.composite(img, glow, mask)
        size = 96 * scale
        icon = brand.icon_image(size)
        top = int(img.height * 0.36)
        img.paste(icon, ((img.width - size) // 2, top), icon)
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(str(FONT), 26 * scale)
        tw = draw.textlength("Dielify", font=font)
        draw.text(((img.width - tw) / 2, top + size + 14 * scale), "Dielify", font=font, fill="#F2F3F5")
    else:  # small picture, top right of the other pages
        img = Image.new("RGB", img.size, "#FFFFFF")
        icon = brand.icon_image(min(img.size))
        img.paste(icon, ((img.width - icon.width) // 2, (img.height - icon.height) // 2), icon)
    img.save(out)


def tv_banner() -> None:
    """Google TV's launcher shows apps as 320x180 dp banners: the icon and the name, on the app's colours."""
    w, h = 640, 360  # xhdpi
    img = Image.new("RGB", (w, h), brand.BG_BOTTOM)
    glow = Image.new("RGB", (w, h), brand.BG_TOP)
    img = Image.composite(img, glow, Image.linear_gradient("L").rotate(90).resize((w, h)))
    icon = brand.icon_image(200)
    img.paste(icon, (54, (h - 200) // 2), icon)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT), 92)
    draw.text((282, h // 2), "Dielify", font=font, fill="#F2F3F5", anchor="lm")
    out = RES / "drawable-xhdpi"
    out.mkdir(exist_ok=True)
    img.save(out / "tv_banner.png")


def main() -> None:
    android()
    tv_banner()
    (ROOT / "src/dielify/ui/logo.svg").write_text(brand.svg(64, tile=False) + "\n", encoding="utf-8")
    pkg = ROOT / "packaging"
    for s in (1, 2):
        wizard(164, 314, s, pkg / f"wizard-large-{s}00.bmp", True)
        wizard(55, 55, s, pkg / f"wizard-small-{s}00.bmp", False)
    out = ROOT / "docs/design/brand"
    out.mkdir(parents=True, exist_ok=True)
    brand.icon_image(512).save(out / "icon.png")
    print("ok")


if __name__ == "__main__":
    main()
