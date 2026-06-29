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

# Heuristic weights (higher score == better placement).
#
# These are the well-known El-Tetris weights — near-optimal for *clearing rows*
# while keeping the stack low. In a 400-piece benchmark they clear ~0.39 lines
# per piece (the theoretical max is 0.40) and hold the peak to ~5 of 20 rows.
#
# The wells / max-height knobs below are intentionally 0. It is tempting to add
# them so the AI never leaves an open side column, but benchmarking showed that
# BACKFIRES: that open column is how good play sets up clears, so penalising it
# made the AI clear LESS and build HIGHER. Leave them at 0 unless you re-measure.
W_LINES = 0.760666     # reward each row this placement clears
W_AGG_HEIGHT = -0.510066   # penalise total stack height (stay low)
W_HOLES = -0.35663     # penalise buried gaps (very hard to clear)
W_BUMPINESS = -0.184483    # penalise an uneven surface
W_WELLS = 0.0          # penalise deep side/edge gaps (off — see note above)
W_MAX_HEIGHT = 0.0     # penalise the tallest column (off — see note above)


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
    # wells: how far each column sits below its lowest neighbour (walls count as
    # full height), summed — a big number means a deep gap / lopsided side build.
    wells = 0
    for x in range(COLS):
        left = heights[x - 1] if x > 0 else ROWS
        right = heights[x + 1] if x < COLS - 1 else ROWS
        depth = min(left, right) - heights[x]
        if depth > 0:
            wells += depth
    return heights, holes, agg, bump, wells


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

            heights, holes, agg, bump, wells = _metrics(grid)
            max_h = max(heights) if heights else 0
            score = (
                W_LINES * lines
                + W_AGG_HEIGHT * agg
                + W_MAX_HEIGHT * max_h
                + W_BUMPINESS * bump
                + W_HOLES * holes
                + W_WELLS * wells
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
