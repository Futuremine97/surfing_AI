#!/usr/bin/env python3
"""Render the Surfing AI app icon — a modern, flat California / San Diego
sunset-surf mark — and every derived asset (PNG set, .icns, .ico, the
menu-bar template glyph, and the web mark.svg).

  python3 scripts/make_icon.py

Pure Pillow, no SVG rasterizer needed. Art is drawn at 4x and downscaled
for clean anti-aliasing.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "desktop" / "src-tauri" / "icons"
MENUBAR_DIR = ROOT / "desktop" / "menubar" / "assets"
WEB_MARK = ROOT / "web" / "mark.svg"

S = 1024          # final icon size
SS = 4            # supersample factor
W = S * SS        # working size


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def vgradient(size, stops):
    """Vertical gradient. stops = [(pos0,(r,g,b)), ...] with pos in 0..1."""
    w, h = size
    img = Image.new("RGB", (1, h))
    px = img.load()
    stops = sorted(stops)
    for y in range(h):
        t = y / (h - 1)
        # find bracketing stops
        lo = stops[0]
        hi = stops[-1]
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0]:
                lo, hi = stops[i], stops[i + 1]
                break
        span = (hi[0] - lo[0]) or 1
        local = (t - lo[0]) / span
        px[0, y] = lerp(lo[1], hi[1], local)
    return img.resize((w, h))


def squircle_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def draw_sun(layer, cx, cy, r, core, glow):
    """Soft radial sun: a blurred glow + a crisp disk."""
    glow_img = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_img)
    gd.ellipse([cx - r * 2.6, cy - r * 2.6, cx + r * 2.6, cy + r * 2.6],
               fill=glow + (170,))
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(r * 0.8))
    layer.alpha_composite(glow_img)
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=core + (255,))


def wave_band(draw, base_y, amp, period, phase, thickness, color, width):
    """A horizontal sinus band (filled) used for stacked ocean swells."""
    top = []
    bot = []
    step = max(2, width // 220)
    for x in range(0, width + step, step):
        y = base_y + amp * math.sin((x / period) * 2 * math.pi + phase)
        top.append((x, y))
        bot.append((x, y + thickness))
    poly = top + bot[::-1]
    draw.polygon(poly, fill=color)


def frond(draw, ox, oy, angle, length, curl, width, color):
    """A tapered palm frond as a filled blade along a curved spine."""
    pts_l, pts_r = [], []
    n = 26
    for i in range(n + 1):
        t = i / n
        # spine bends downward (curl) as it extends
        a = math.radians(angle) + curl * t
        x = ox + math.cos(a) * length * t
        y = oy + math.sin(a) * length * t
        w = width * (1 - t) ** 0.7 * (0.25 + 0.75 * math.sin(t * math.pi))
        nx, ny = math.sin(a), -math.cos(a)
        pts_l.append((x + nx * w, y + ny * w))
        pts_r.append((x - nx * w, y - ny * w))
    draw.polygon(pts_l + pts_r[::-1], fill=color)


def palm(layer, base_x, base_y, scale, color):
    d = ImageDraw.Draw(layer)
    # curved tapered trunk (lean to the right)
    spine = []
    for i in range(31):
        t = i / 30
        x = base_x + (0.06 * math.sin(t * 1.7) + 0.18 * t) * scale * 3.2
        y = base_y - t * scale * 6.6
        spine.append((x, y))
    left, right = [], []
    for i, (x, y) in enumerate(spine):
        t = i / 30
        w = (1 - t) * scale * 0.42 + scale * 0.10
        left.append((x - w, y))
        right.append((x + w, y))
    d.polygon(left + right[::-1], fill=color)
    crown = spine[-1]
    # long, gracefully drooping fronds fanning from the crown
    specs = [(-182, 1.5), (-158, 1.7), (-132, 1.7), (-104, 1.5),
             (-74, 1.5), (-46, 1.7), (-20, 1.7), (4, 1.5)]
    for ang, curl in specs:
        frond(d, crown[0], crown[1] - scale * 0.1, ang, scale * 4.7, curl,
              scale * 0.46, color)
    # small coconut cluster under the crown
    for dx, dy in [(-0.12, 0.18), (0.16, 0.16)]:
        r = scale * 0.13
        d.ellipse([crown[0] + dx * scale - r, crown[1] + dy * scale - r,
                   crown[0] + dx * scale + r, crown[1] + dy * scale + r],
                  fill=color)


def build_scene():
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))

    horizon = int(W * 0.60)

    # --- sky ---
    sky = vgradient((W, horizon), [
        (0.0, (74, 42, 120)),    # dusk purple
        (0.45, (255, 99, 132)),  # coral pink
        (0.80, (255, 138, 92)),  # warm orange
        (1.0, (255, 196, 120)),  # peach at horizon
    ]).convert("RGBA")
    img.paste(sky, (0, 0))

    # --- sun just above the horizon ---
    draw_sun(img, int(W * 0.50), int(horizon * 0.86), int(W * 0.115),
             core=(255, 233, 168), glow=(255, 178, 96))

    # --- ocean ---
    ocean = vgradient((W, W - horizon), [
        (0.0, (39, 201, 199)),   # turquoise near horizon
        (0.5, (20, 124, 196)),
        (1.0, (10, 64, 128)),    # deep blue
    ]).convert("RGBA")
    img.paste(ocean, (0, horizon))

    od = ImageDraw.Draw(img)
    # sun reflection shimmer on the water
    refl = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    rd = ImageDraw.Draw(refl)
    for i in range(7):
        yy = horizon + int((i + 1) * W * 0.022)
        half = int(W * (0.11 - i * 0.012))
        rd.rounded_rectangle([W // 2 - half, yy - 6, W // 2 + half, yy + 6],
                             radius=8, fill=(255, 224, 170, 150))
    img.alpha_composite(refl)

    # stacked swells + foam crest (the "surf")
    wave_band(od, int(W * 0.70), W * 0.012, W * 0.55, 0.0,
              int(W * 0.10), (13, 90, 160, 255), W)
    wave_band(od, int(W * 0.78), W * 0.016, W * 0.48, 1.7,
              int(W * 0.12), (16, 110, 190, 255), W)
    wave_band(od, int(W * 0.74), W * 0.013, W * 0.50, 0.8,
              int(W * 0.020), (233, 251, 255, 235), W)  # foam line
    wave_band(od, int(W * 0.865), W * 0.018, W * 0.42, 3.1,
              int(W * 0.16), (8, 62, 124, 255), W)

    # --- palm silhouette on the left ---
    palm(img, int(W * 0.165), int(W * 0.74), W * 0.052, (16, 28, 46, 255))

    return img


def main():
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    MENUBAR_DIR.mkdir(parents=True, exist_ok=True)

    scene = build_scene()

    # squircle mask (Big-Sur style, small transparent gutter)
    margin = int(W * 0.045)
    inner = W - margin * 2
    radius = int(inner * 0.225)
    mask_inner = squircle_mask(inner, radius)
    mask = Image.new("L", (W, W), 0)
    mask.paste(mask_inner, (margin, margin))

    icon = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    icon.paste(scene, (0, 0), mask)

    # subtle top sheen for depth
    sheen = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sheen)
    sd.ellipse([int(-W * 0.2), int(-W * 0.55), int(W * 1.2), int(W * 0.35)],
               fill=(255, 255, 255, 26))
    icon.alpha_composite(Image.composite(
        sheen, Image.new("RGBA", (W, W), (0, 0, 0, 0)), mask))

    icon = icon.resize((S, S), Image.LANCZOS)

    # ---- exports ----
    icon.save(ICON_DIR / "icon.png")
    for sz in (256, 128, 64, 32, 16):
        icon.resize((sz, sz), Image.LANCZOS).save(
            ICON_DIR / f"{sz}x{sz}.png")
    icon.save(ICON_DIR / "icon.icns")
    icon.save(ICON_DIR / "icon.ico",
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64),
                     (128, 128), (256, 256)])

    # preview on a neutral checker-free card for review
    prev = Image.new("RGBA", (S + 160, S + 160), (236, 238, 242, 255))
    prev.alpha_composite(icon, (80, 80))
    prev.convert("RGB").save(ICON_DIR / "icon_preview.png")

    # ---- menu-bar template glyph (monochrome, alpha) ----
    make_menubar_glyph()

    # ---- web mark ----
    WEB_MARK.write_text(WEB_MARK_SVG, encoding="utf-8")

    print("wrote:")
    for p in sorted(ICON_DIR.glob("*")):
        print("  ", p.relative_to(ROOT))
    for p in sorted(MENUBAR_DIR.glob("*")):
        print("  ", p.relative_to(ROOT))
    print("  ", WEB_MARK.relative_to(ROOT))


def make_menubar_glyph():
    """Black template wave for NSStatusItem (macOS recolors template imgs)."""
    base = 44
    for scale, name in ((1, "menubar_template.png"),
                        (2, "menubar_template@2x.png")):
        n = base * scale
        g = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(g)
        th = max(2, int(n * 0.085))
        for k, yb in enumerate((0.42, 0.60)):
            pts = []
            for i in range(n + 1):
                x = i
                y = n * yb + math.sin((i / n) * 2 * math.pi + k * 1.6) \
                    * n * 0.11
                pts.append((x, y))
            d.line(pts, fill=(0, 0, 0, 255), width=th, joint="curve")
        # small sun dot
        r = int(n * 0.07)
        d.ellipse([n * 0.74 - r, n * 0.27 - r, n * 0.74 + r, n * 0.27 + r],
                  fill=(0, 0, 0, 255))
        g.save(MENUBAR_DIR / name)


WEB_MARK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" role="img" aria-label="Surfing AI">
  <defs>
    <linearGradient id="sky" x1="24" y1="3" x2="24" y2="30" gradientUnits="userSpaceOnUse">
      <stop stop-color="#4a2a78"/>
      <stop offset=".5" stop-color="#ff6384"/>
      <stop offset="1" stop-color="#ffb878"/>
    </linearGradient>
    <linearGradient id="sea" x1="24" y1="29" x2="24" y2="45" gradientUnits="userSpaceOnUse">
      <stop stop-color="#27c9c7"/>
      <stop offset="1" stop-color="#0a4080"/>
    </linearGradient>
    <clipPath id="sq"><rect x="2" y="2" width="44" height="44" rx="13"/></clipPath>
  </defs>
  <g clip-path="url(#sq)">
    <rect x="2" y="2" width="44" height="28" fill="url(#sky)"/>
    <circle cx="24" cy="25" r="6" fill="#ffe7a8"/>
    <rect x="2" y="29" width="44" height="17" fill="url(#sea)"/>
    <path d="M2 36c8-3 14 3 22 0s14-3 20 0v10H2Z" fill="#0d5aa0"/>
    <path d="M2 38c8-2.5 14 2.5 22 0s14-2.5 20 0" fill="none" stroke="#e9fbff" stroke-width="1.2"/>
    <path d="M11 39c-.4-5 .4-9 1.2-12 .3 2.6 2 4 4.6 4.2-2.2.3-3.4 1.6-3.9 3.9-.3-1.9-1-2.9-1.9-3.1Z" fill="#101c2e"/>
  </g>
  <rect x="2" y="2" width="44" height="44" rx="13" fill="none" stroke="#ffffff" stroke-opacity=".12"/>
</svg>
"""


if __name__ == "__main__":
    main()
