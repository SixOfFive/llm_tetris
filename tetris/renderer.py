"""All drawing.  The renderer is stateless beyond its fonts/assets; the main
loop hands it the two games plus a small context object each frame.
"""

from __future__ import annotations

from typing import List, Optional

import pygame

from . import constants as C
from .board import EMPTY
from .pieces import SHAPES


def _grad_rect(surf, rect, top, bottom):
    x, y, w, h = rect
    for i in range(h):
        t = i / max(1, h - 1)
        col = tuple(int(top[k] + (bottom[k] - top[k]) * t) for k in range(3))
        pygame.draw.line(surf, col, (x, y + i), (x + w, y + i))


class Renderer:
    def __init__(self, screen: pygame.Surface, assets):
        self.screen = screen
        self.assets = assets
        self.f_title = pygame.font.SysFont("Consolas", 24, bold=True)
        self.f_big = pygame.font.SysFont("Consolas", 40, bold=True)
        self.f_h = pygame.font.SysFont("Consolas", 18, bold=True)
        self.f = pygame.font.SysFont("Consolas", 15)
        self.f_s = pygame.font.SysFont("Consolas", 13)

    # -- small helpers ------------------------------------------------------
    def _text(self, s, font, color, x, y, center=False, right=False):
        img = font.render(s, True, color)
        r = img.get_rect()
        if center:
            r.midtop = (x, y)
        elif right:
            r.topright = (x, y)
        else:
            r.topleft = (x, y)
        self.screen.blit(img, r)
        return r

    def _panel(self, rect, title=None):
        x, y, w, h = rect
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        s.fill((*C.PANEL_BG, 235))
        self.screen.blit(s, (x, y))
        pygame.draw.rect(self.screen, C.PANEL_BORDER, rect, 1, border_radius=4)
        if title:
            self._text(title, self.f_h, C.ACCENT, x + 12, y + 8)

    def _block(self, name, gx, gy, ox, oy):
        if gy < 0:
            return
        self.screen.blit(self.assets.block(name), (ox + gx * C.CELL, oy + gy * C.CELL))

    # -- board --------------------------------------------------------------
    def draw_board(self, x0, y0, game, active=True):
        board_rect = (x0, y0, C.BOARD_PX_W, C.BOARD_PX_H)
        well = pygame.Surface((C.BOARD_PX_W, C.BOARD_PX_H))
        well.fill((10, 12, 18))
        self.screen.blit(well, (x0, y0))

        # grid lines
        for cx in range(C.COLS + 1):
            pygame.draw.line(self.screen, C.GRID_LINE,
                             (x0 + cx * C.CELL, y0), (x0 + cx * C.CELL, y0 + C.BOARD_PX_H))
        for cy in range(C.ROWS + 1):
            pygame.draw.line(self.screen, C.GRID_LINE,
                             (x0, y0 + cy * C.CELL), (x0 + C.BOARD_PX_W, y0 + cy * C.CELL))

        # locked cells
        for ry, row in enumerate(game.board.grid):
            for cx, cell in enumerate(row):
                if cell != EMPTY:
                    self._block(cell, cx, ry, x0, y0)

        # ghost + current piece
        if game.current is not None and not game.dead:
            p = game.current
            gy = game.ghost_py()
            for (cx, cyy) in p.cells(p.rot, p.px, gy):
                if cyy >= 0:
                    pygame.draw.rect(self.screen, C.GHOST,
                                     (x0 + cx * C.CELL + 2, y0 + cyy * C.CELL + 2,
                                      C.CELL - 4, C.CELL - 4), 2, border_radius=3)
            for (cx, cyy) in p.cells():
                self._block(p.name, cx, cyy, x0, y0)

        pygame.draw.rect(self.screen, C.PANEL_BORDER if active else (60, 30, 30),
                         board_rect, 2)

    def _mini_piece(self, name, cx, cy, scale=18):
        cells = SHAPES[name][0]
        xs = [c[0] for c in cells]
        ys = [c[1] for c in cells]
        w = (max(xs) - min(xs) + 1) * scale
        h = (max(ys) - min(ys) + 1) * scale
        ox = cx - w // 2 - min(xs) * scale
        oy = cy - h // 2 - min(ys) * scale
        tile = self.assets.block(name, scale)
        for (x, y) in cells:
            self.screen.blit(tile, (ox + x * scale, oy + y * scale))

    # -- HUD beside a board -------------------------------------------------
    def draw_hud(self, hx, game, label_lines):
        # "NEXT" box
        nb = (hx, C.BOARD_TOP, C.HUD_W, 96)
        self._panel(nb, "NEXT")
        self._mini_piece(game.next_name, hx + C.HUD_W // 2, C.BOARD_TOP + 60)

        # stats box
        sb = (hx, C.BOARD_TOP + 108, C.HUD_W, 150)
        self._panel(sb)
        yy = C.BOARD_TOP + 118
        for lab, val in label_lines:
            self._text(lab, self.f_s, C.TEXT_DIM, hx + 12, yy)
            self._text(str(val), self.f_h, C.TEXT, hx + C.HUD_W - 12, yy - 2, right=True)
            yy += 30

        # incoming garbage meter
        inc = game.incoming_count()
        mb_y = C.BOARD_TOP + 108 + 150 + 12
        self._text("INCOMING", self.f_s, C.TEXT_DIM, hx + 12, mb_y)
        bar = (hx + 12, mb_y + 20, C.HUD_W - 24, 18)
        pygame.draw.rect(self.screen, (40, 24, 28), bar, border_radius=3)
        if inc > 0:
            frac = min(1.0, inc / 16.0)
            pygame.draw.rect(self.screen, C.LOSE_COLOR,
                             (bar[0], bar[1], int(bar[2] * frac), bar[3]), border_radius=3)
            self._text(f"{inc}", self.f_s, C.TEXT, hx + C.HUD_W - 14, mb_y + 21, right=True)

    # -- wrapped text -------------------------------------------------------
    def _wrap(self, text, font, max_w):
        words = text.split(" ")
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if font.size(trial)[0] <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def draw_reply_panel(self, llm_status, llm_log: List[str], model_name):
        x, y, w, h = C.LLM_PANEL
        self._panel((x, y, w, h), f"{model_name}  ·  REPLIES")
        # status line
        self._text(llm_status, self.f, C.THINK_COLOR, x + 12, y + 32)
        # log, newest at bottom
        line_h = 17
        area_top = y + 56
        area_bottom = y + h - 8
        rendered = []
        for entry in reversed(llm_log):
            for wl in reversed(self._wrap(entry, self.f_s, w - 28)):
                rendered.append(wl)
        rendered = rendered[: max(0, (area_bottom - area_top) // line_h)]
        yy = area_bottom - line_h
        for wl in rendered:
            color = C.TEXT if not wl.startswith("· ") else C.TEXT_DIM
            self._text(wl, self.f_s, color, x + 14, yy)
            yy -= line_h

    def draw_help_panel(self):
        x, y, w, h = C.PLAYER_PANEL
        self._panel((x, y, w, h), "YOU  ·  CONTROLS")
        lines = [
            "<-  ->   move piece",
            "Up / X   rotate clockwise",
            "Z / Ctrl rotate counter-clockwise",
            "Down     soft drop",
            "Space    hard drop",
            "P pause   ·   R restart   ·   Esc quit",
        ]
        yy = y + 38
        for ln in lines:
            self._text(ln, self.f, C.TEXT, x + 16, yy)
            yy += 23

    # -- overlays -----------------------------------------------------------
    def draw_center(self, winner: Optional[str]):
        cx = C.CENTER_X
        pygame.draw.line(self.screen, C.PANEL_BORDER, (cx, C.BOARD_TOP),
                         (cx, C.BOARD_TOP + C.BOARD_PX_H), 1)
        self._text("VS", self.f_title, C.ACCENT, cx, C.BOARD_TOP + C.BOARD_PX_H // 2 - 14,
                   center=True)

    def banner(self, x0, text, color):
        s = pygame.Surface((C.BOARD_PX_W, 70), pygame.SRCALPHA)
        s.fill((0, 0, 0, 180))
        self.screen.blit(s, (x0, C.BOARD_TOP + C.BOARD_PX_H // 2 - 35))
        self._text(text, self.f_big, color, x0 + C.BOARD_PX_W // 2,
                   C.BOARD_TOP + C.BOARD_PX_H // 2 - 26, center=True)

    # -- top level ----------------------------------------------------------
    def render(self, player, llm, *, llm_status, llm_log, winner, state, model_name):
        self.screen.blit(self.assets.background, (0, 0))

        # titles
        self._text("YOU", self.f_title, C.TEXT, C.PLAYER_BOARD_X + C.BOARD_PX_W // 2, 30,
                   center=True)
        self._text(model_name, self.f_title, C.THINK_COLOR,
                   C.LLM_BOARD_X + C.BOARD_PX_W // 2, 30, center=True)

        self.draw_board(C.PLAYER_BOARD_X, C.BOARD_TOP, player, active=not player.dead)
        self.draw_board(C.LLM_BOARD_X, C.BOARD_TOP, llm, active=not llm.dead)
        self.draw_center(winner)

        self.draw_hud(C.PLAYER_HUD_X, player, [
            ("LINES", player.lines_cleared),
            ("SENT", player.lines_sent),
            ("PIECES", player.pieces_placed),
        ])
        self.draw_hud(C.LLM_HUD_X, llm, [
            ("LINES", llm.lines_cleared),
            ("SENT", llm.lines_sent),
            ("PIECES", llm.pieces_placed),
        ])

        self.draw_help_panel()
        self.draw_reply_panel(llm_status, llm_log, model_name)

        if state == "over":
            if winner == "player":
                self.banner(C.PLAYER_BOARD_X, "WIN!", C.WIN_COLOR)
                self.banner(C.LLM_BOARD_X, "LOSE", C.LOSE_COLOR)
            elif winner == "llm":
                self.banner(C.PLAYER_BOARD_X, "LOSE", C.LOSE_COLOR)
                self.banner(C.LLM_BOARD_X, "WIN!", C.WIN_COLOR)
            self._text("Press  R  to play again", self.f_h, C.TEXT,
                       C.CENTER_X, C.BOARD_TOP + C.BOARD_PX_H + 4, center=True)
        elif state == "paused":
            self.banner(C.PLAYER_BOARD_X, "PAUSED", C.ACCENT)
            self.banner(C.LLM_BOARD_X, "PAUSED", C.ACCENT)
            self._text("Press  P  to start / resume", self.f_h, C.TEXT,
                       C.CENTER_X, C.BOARD_TOP + C.BOARD_PX_H + 4, center=True)
