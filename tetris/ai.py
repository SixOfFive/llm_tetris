"""Heuristic placement engine.

Two jobs:
  1. Enumerate every legal final placement of the current piece, with the
     consequences of each (lines cleared, holes added, resulting height).
     This list is handed to the LLM as its menu of options.
  2. Score placements with a classic Tetris evaluation so we always have a
     strong fallback move when the LLM is unavailable, slow, or replies with
     something illegal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .board import Board, EMPTY
from .constants import COLS, ROWS
from .pieces import Piece, SHAPES

# El-Tetris style weights (higher score == better placement).
W_AGG_HEIGHT = -0.510066
W_LINES = 0.760666
W_HOLES = -0.35663
W_BUMPINESS = -0.184483


@dataclass
class Placement:
    id: int
    rot: int
    px: int
    py: int
    lines: int          # lines this placement would clear
    holes_after: int    # total holes in the resulting stack
    max_height: int     # tallest column afterward
    bumpiness: int
    agg_height: int
    score: float


def _metrics(grid: List[List]):
    heights = [0] * COLS
    holes = 0
    for x in range(COLS):
        seen = False
        for y in range(ROWS):
            if grid[y][x] != EMPTY:
                if not seen:
                    heights[x] = ROWS - y
                seen = True
            elif seen:
                holes += 1
    agg = sum(heights)
    bump = sum(abs(heights[i] - heights[i + 1]) for i in range(COLS - 1))
    return heights, holes, agg, bump


def enumerate_placements(board: Board, piece: Piece) -> List[Placement]:
    """All distinct legal hard-drop placements, scored and de-duplicated."""
    out: List[Placement] = []
    seen_cells = set()
    base = board.snapshot()
    for rot in range(4):
        shape = SHAPES[piece.name][rot]
        min_x = min(c[0] for c in shape)
        max_x = max(c[0] for c in shape)
        for px in range(-min_x, COLS - max_x):
            py = board.drop_py(piece, rot, px)
            cells = piece.cells(rot, px, py)
            if board.collides(cells):
                continue
            if any(y < 0 for (_, y) in cells):
                continue  # would lock out — not an offered option
            key = frozenset(cells)
            if key in seen_cells:
                continue
            seen_cells.add(key)

            # Simulate the lock + line clear on a scratch grid.
            grid = [row[:] for row in base]
            for (x, y) in cells:
                grid[y][x] = piece.name
            kept = [row for row in grid if any(c == EMPTY for c in row)]
            lines = ROWS - len(kept)
            if lines:
                grid = [[EMPTY] * COLS for _ in range(lines)] + kept

            heights, holes, agg, bump = _metrics(grid)
            score = (
                W_AGG_HEIGHT * agg
                + W_LINES * lines
                + W_HOLES * holes
                + W_BUMPINESS * bump
            )
            out.append(
                Placement(
                    id=len(out),
                    rot=rot,
                    px=px,
                    py=py,
                    lines=lines,
                    holes_after=holes,
                    max_height=max(heights) if heights else 0,
                    bumpiness=bump,
                    agg_height=agg,
                    score=score,
                )
            )
    return out


def best_placement(placements: List[Placement]) -> Placement | None:
    if not placements:
        return None
    return max(placements, key=lambda p: p.score)
