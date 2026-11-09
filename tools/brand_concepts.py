"""0.9.9 stage 4: app icon concepts for Josh to pick from.

Every icon is drawn on Android's 108-unit adaptive-icon canvas (launchers show the middle
72, the safe zone is a 66 circle round the centre), so the chosen one turns straight into
the phone's vector drawables and the PC's .ico / tray image.

python tools/brand_concepts.py  ->  docs/design/brand/board.html + board.png
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "design" / "brand"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def grad(id_, stops, x1=18, y1=18, x2=90, y2=90):
    s = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in stops)
    return (f'<linearGradient id="{id_}" gradientUnits="userSpaceOnUse" x1="{x1}" y1="{y1}" '
            f'x2="{x2}" y2="{y2}">{s}</linearGradient>')


WARM = [(0, "#FF9A5B"), (0.5, "#FF5A5F"), (1, "#C9246B")]


def record_d(p):
    return (grad(p + "g", WARM),
            f'<rect width="108" height="108" fill="url(#{p}g)"/>'
            '<path d="M36,33 H52 A21,21 0 0 1 52,75 H36 Z" fill="#fff"/>'
            f'<circle cx="52" cy="54" r="15.5" fill="none" stroke="url(#{p}g)" stroke-width="1.3" opacity=".45"/>'
            f'<circle cx="52" cy="54" r="11" fill="none" stroke="url(#{p}g)" stroke-width="1.3" opacity=".45"/>'
            f'<circle cx="52" cy="54" r="6.2" fill="url(#{p}g)"/>'
            '<circle cx="52" cy="54" r="1.8" fill="#fff"/>')


def wave_d(p):
    bars, x = [], 33.0
    while x < 70:
        mid = x + 2.25
        h = 44 if mid <= 46 else 2 * math.sqrt(max(0, 22 ** 2 - (mid - 46) ** 2))
        if h > 6:
            bars.append(f'<rect x="{x:.1f}" y="{54 - h / 2:.1f}" width="4.5" height="{h:.1f}" rx="2.25" '
                        f'fill="url(#{p}b)"/>')
        x += 6.9
    return (grad(p + "g", [(0, "#1D1824"), (1, "#0E0F12")])
            + grad(p + "b", [(0, "#FFB35B"), (0.5, "#FF5A5F"), (1, "#B84DFF")], 54, 33, 54, 75),
            f'<rect width="108" height="108" fill="url(#{p}g)"/>' + "".join(bars))


def afterglow(p):
    stripes = "".join(f'<rect x="20" y="{y}" width="68" height="{h}" fill="url(#{p}g)"/>'
                      for y, h in ((57, 1.4), (62, 2.4), (67.6, 3.4), (73.8, 4.4)))
    return (grad(p + "g", [(0, "#2B1640"), (1, "#120F1F")])
            + grad(p + "s", [(0, "#FFD166"), (0.4, "#FF8A5B"), (0.7, "#FF4D6D"), (1, "#C2307A")], 54, 29, 54, 79),
            f'<rect width="108" height="108" fill="url(#{p}g)"/>'
            f'<circle cx="54" cy="54" r="25" fill="url(#{p}s)"/>' + stripes)


def play_d(p):
    return (grad(p + "g", WARM),
            f'<rect width="108" height="108" fill="url(#{p}g)"/>'
            '<path fill="#fff" fill-rule="evenodd" d="M35,32 H53 A22,22 0 0 1 53,76 H35 Z '
            'M46,44.5 L46,63.5 Q46,66 48.2,64.8 L62.5,56.2 Q64.6,54 62.5,51.8 L48.2,43.2 Q46,42 46,44.5 Z"/>')


def note_d(p):
    return (grad(p + "g", [(0, "#6A4CF5"), (0.55, "#E2457A"), (1, "#FF8A5B")]),
            f'<rect width="108" height="108" fill="url(#{p}g)"/>'
            '<path fill="#fff" fill-rule="evenodd" d="M47,50 a13,13 0 1 0 0.01,0 Z M47,58.5 a4.5,4.5 0 1 1 -0.01,0 Z"/>'
            '<rect x="56" y="30" width="7" height="34" rx="1" fill="#fff"/>'
            '<path fill="#fff" d="M60,30 H63 C63,38 76,40 75,51 C73,45 68,42.5 63,42.5 Z"/>')


def cassette(p):
    return (grad(p + "g", [(0, "#FFD166"), (1, "#FF6B5B")]),
            f'<rect width="108" height="108" fill="url(#{p}g)"/>'
            '<rect x="29" y="37" width="50" height="34" rx="5" fill="#16181C"/>'
            '<rect x="33" y="41" width="42" height="9" rx="2" fill="#fff"/>'
            '<rect x="36" y="44.5" width="20" height="2" rx="1" fill="#FF5A5F"/>'
            '<rect x="47" y="54" width="14" height="8" rx="2" fill="#3A3F47"/>'
            '<circle cx="42" cy="58" r="5" fill="#fff"/><circle cx="42" cy="58" r="1.8" fill="#16181C"/>'
            '<circle cx="66" cy="58" r="5" fill="#fff"/><circle cx="66" cy="58" r="1.8" fill="#16181C"/>'
            '<path d="M37,71 L40,65.5 H68 L71,71 Z" fill="#2A2E35"/>')


CONCEPTS = [
    ("A", "Record D", "The D's round side is a record, with grooves and a label.", record_d),
    ("B", "Wave D", "A D made of sound bars, like the bars on the song that's playing.", wave_d),
    ("C", "Afterglow", "A retro sunset: warm, no letters, stands out on a home screen.", afterglow),
    ("D", "Play D", "A D with a play button cut out of it: Dielify, press play.", play_d),
    ("E", "Note d", "A music note that is also a small d.", note_d),
    ("F", "Mixtape", "A cassette: your own mixes, a bit playful.", cassette),
]


def svg(fn, key, size, shape="squircle"):
    p = f"{key}{size}{shape}"
    defs, body = fn(p)
    clip = {"squircle": '<rect x="18" y="18" width="72" height="72" rx="17"/>',
            "circle": '<circle cx="54" cy="54" r="36"/>',
            "square": '<rect x="18" y="18" width="72" height="72" rx="6"/>'}[shape]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="18 18 72 72">'
            f'<defs>{defs}<clipPath id="{p}c">{clip}</clipPath></defs><g clip-path="url(#{p}c)">{body}</g></svg>')


def card(key, name, why, fn):
    small = "".join(svg(fn, key, s, "square") for s in (48, 32, 16))
    home = "".join('<span class="ph"></span>' if i != 1 else svg(fn, key, 54, "circle") for i in range(4))
    return f"""
<section class="card">
  <div class="head"><b>{key}</b><div><h2>{name}</h2><p>{why}</p></div></div>
  <div class="row">
    <div class="big">{svg(fn, key, 168)}</div>
    <div class="col">
      <div class="home">{home}<div class="labels"><i></i><i>Dielify</i><i></i><i></i></div></div>
      <div class="sizes"><div class="dark">{small}</div><div class="light">{small}</div></div>
      <small>PC sizes: 48 / 32 / 16 px (taskbar, tray)</small>
    </div>
    <div class="splash">{svg(fn, key, 76, "circle")}<div class="word">Dielify</div></div>
  </div>
</section>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    font = (ROOT / "src/dielify/ui/fonts/inter-latin.woff2").as_uri()
    html = f"""<!doctype html><meta charset="utf-8"><style>
@font-face {{ font-family: Inter; src: url({font}) format('woff2'); font-weight: 100 900; }}
body {{ margin: 0; background: #0E0F12; color: #F2F3F5; font: 14px Inter, sans-serif; padding: 36px; width: 1328px; }}
h1 {{ font-size: 34px; font-weight: 800; letter-spacing: -.03em; margin: 0 0 4px; }}
.lead {{ color: #9AA1AB; margin: 0 0 28px; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
.card {{ background: #16181C; border-radius: 20px; padding: 22px; }}
.head {{ display: flex; gap: 14px; align-items: center; margin-bottom: 18px; }}
.head b {{ width: 40px; height: 40px; border-radius: 50%; background: #FF5A5F; display: grid; place-items: center; font-size: 20px; font-weight: 800; }}
h2 {{ margin: 0; font-size: 20px; font-weight: 800; letter-spacing: -.02em; }}
.head p {{ margin: 2px 0 0; color: #9AA1AB; }}
.row {{ display: flex; gap: 18px; align-items: center; }}
.big svg {{ display: block; filter: drop-shadow(0 10px 24px rgba(0,0,0,.5)); }}
.col {{ display: flex; flex-direction: column; gap: 10px; }}
.home {{ background: linear-gradient(135deg, #3B5B7A, #6E8B6A); border-radius: 14px; padding: 12px 12px 8px; display: grid; grid-template-columns: repeat(4, 54px); gap: 0 10px; }}
.home .ph {{ width: 54px; height: 54px; border-radius: 50%; background: rgba(255,255,255,.28); }}
.labels {{ display: contents; }}
.labels i {{ font-style: normal; font-size: 10px; text-align: center; color: #fff; padding-top: 4px; min-height: 12px; }}
.sizes {{ display: flex; border-radius: 10px; overflow: hidden; }}
.sizes > div {{ display: flex; gap: 10px; align-items: center; padding: 8px 10px; }}
.dark {{ background: #202020; }} .light {{ background: #EDEDED; }}
small {{ color: #6B727C; font-size: 11px; }}
.splash {{ margin-left: auto; width: 116px; height: 228px; border-radius: 18px; background: #0E0F12; border: 2px solid #2A2E35;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; }}
.word {{ font-weight: 800; letter-spacing: -.03em; font-size: 16px; }}
</style>
<h1>Dielify icon: pick one</h1>
<p class="lead">Each shows the phone icon, how it sits on a home screen, the PC sizes on dark and light, and the start-up screen.
Colours and details can still be tweaked, or two ideas mixed.</p>
<div class="grid">{"".join(card(*c) for c in CONCEPTS)}</div>"""
    page = OUT / "board.html"
    page.write_text(html, encoding="utf-8")
    profile = ROOT / "build" / "chrome-shots"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}",
                    "--force-device-scale-factor=1", "--window-size=1400,1210", f"--screenshot={OUT / 'board.png'}",
                    page.as_uri()], check=True, capture_output=True)
    print(OUT / "board.png")


if __name__ == "__main__":
    main()
