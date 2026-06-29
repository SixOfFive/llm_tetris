"""Load the generated PNG assets into pygame surfaces (scaled to cell size)."""

from __future__ import annotations

import os

import pygame

from .constants import ASSET_DIR, CELL, COLORS, WINDOW_H, WINDOW_W


class Assets:
    def __init__(self):
        # Generate the PNGs on first run if they are missing.
        from generate_assets import ensure_assets
        self.dir = ensure_assets(force=False)

        self.blocks = {}
        for name in COLORS:
            path = os.path.join(self.dir, f"block_{name}.png")
            img = pygame.image.load(path).convert_alpha()
            self.blocks[name] = pygame.transform.smoothscale(img, (CELL, CELL))

        bg_path = os.path.join(self.dir, "background.png")
        bg = pygame.image.load(bg_path).convert()
        self.background = pygame.transform.smoothscale(bg, (WINDOW_W, WINDOW_H))

    def block(self, name: str, size: int | None = None) -> pygame.Surface:
        surf = self.blocks[name]
        if size is not None and size != CELL:
            return pygame.transform.smoothscale(surf, (size, size))
        return surf
