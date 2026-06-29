"""Procedurally generate all image assets (public-domain, our own output).

Run directly (``python generate_assets.py``) or let the game call
``ensure_assets()`` on startup.  Produces, under ``assets/``:

  * block_<I,O,T,S,Z,J,L,G>.png  -- 32px glossy bevelled tetromino tiles
  * background.png               -- full-window vertical gradient + vignette
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

from tetris.constants import (ASSET_DIR, BG_BOTTOM, BG_TOP, COLORS, WINDOW_H,
                              WINDOW_W)

TILE = 32


def _shade(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color[:3])


def make_block(color) -> Image.Image:
    """A bevelled, glossy square tile for one tetromino colour."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    base = color[:3]

    # Vertical inner gradient (lighter at top -> base toward bottom).
    for y in range(TILE):
        t = y / (TILE - 1)
        f = 1.18 - 0.45 * t
        d.line([(0, y), (TILE - 1, y)], fill=_shade(base, f))

    # Bevel: bright top/left edges, dark bottom/right edges.
    light = _shade(base, 1.6)
    dark = _shade(base, 0.4)
    d.line([(0, 0), (TILE - 1, 0)], fill=light)
    d.line([(0, 0), (0, TILE - 1)], fill=light)
    d.line([(1, 1), (TILE - 2, 1)], fill=_shade(base, 1.35))
    d.line([(1, 1), (1, TILE - 2)], fill=_shade(base, 1.35))
    d.line([(0, TILE - 1), (TILE - 1, TILE - 1)], fill=dark)
    d.line([(TILE - 1, 0), (TILE - 1, TILE - 1)], fill=dark)

    # Crisp outer border so adjacent cells read as separate blocks.
    d.rectangle([0, 0, TILE - 1, TILE - 1], outline=_shade(base, 0.28))

    # Soft diagonal gloss highlight in the upper-left.
    gloss = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    gd.polygon([(3, 3), (TILE // 2, 3), (3, TILE // 2)], fill=(255, 255, 255, 55))
    img = Image.alpha_composite(img, gloss)
    return img


def make_background() -> Image.Image:
    img = Image.new("RGB", (WINDOW_W, WINDOW_H), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(WINDOW_H):
        t = y / (WINDOW_H - 1)
        col = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        d.line([(0, y), (WINDOW_W, y)], fill=col)

    # Faint diagonal vignette darkening toward the corners.
    overlay = Image.new("RGBA", (WINDOW_W, WINDOW_H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    cx, cy = WINDOW_W / 2, WINDOW_H / 2
    maxd = (cx ** 2 + cy ** 2) ** 0.5
    step = 4
    for y in range(0, WINDOW_H, step):
        for x in range(0, WINDOW_W, step):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
            a = int(70 * dist ** 2)
            od.rectangle([x, y, x + step, y + step], fill=(0, 0, 0, a))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img


def ensure_assets(force: bool = False) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, ASSET_DIR)
    os.makedirs(out, exist_ok=True)

    bg_path = os.path.join(out, "background.png")
    if force or not os.path.exists(bg_path):
        make_background().save(bg_path)

    for name, color in COLORS.items():
        path = os.path.join(out, f"block_{name}.png")
        if force or not os.path.exists(path):
            make_block(color).save(path)
    return out


if __name__ == "__main__":
    path = ensure_assets(force=True)
    print(f"Assets written to {path}")
