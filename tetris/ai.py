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
    score: float        # 1-ply score: this placement only
    lookahead: float = 0.0   # 2-ply score: this placement + best next placement


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


def _static_eval(grid: List[List]):
    """Board-shape score (everything except the line-clear reward) plus the
    metrics used to describe a placement."""
    heights, holes, agg, bump, wells = _metrics(grid)
    max_h = max(heights) if heights else 0
    shape = (W_AGG_HEIGHT * agg + W_MAX_HEIGHT * max_h
             + W_BUMPINESS * bump + W_HOLES * holes + W_WELLS * wells)
    return shape, holes, max_h, bump, agg


def _drop_and_clear(base: List[List], piece: Piece, rot: int, px: int, py: int):
    """Lock the piece into a copy of ``base`` and clear full rows.
    Returns (lines_cleared, resulting_grid)."""
    grid = [row[:] for row in base]
    for (x, y) in piece.cells(rot, px, py):
        if 0 <= y < ROWS and 0 <= x < COLS:
            grid[y][x] = piece.name
    kept = [row for row in grid if any(c == EMPTY for c in row)]
    lines = ROWS - len(kept)
    if lines:
        grid = [[EMPTY] * COLS for _ in range(lines)] + kept
    return lines, grid


def enumerate_placements(board: Board, piece: Piece) -> List[Placement]:
    """All distinct legal hard-drop placements, scored (1-ply) and de-duplicated."""
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

            lines, grid = _drop_and_clear(base, piece, rot, px, py)
            shape_score, holes, max_h, bump, agg = _static_eval(grid)
            score = W_LINES * lines + shape_score
            out.append(
                Placement(
                    id=len(out), rot=rot, px=px, py=py, lines=lines,
                    holes_after=holes, max_height=max_h, bumpiness=bump,
                    agg_height=agg, score=score, lookahead=score,
                )
            )
    return out


def _best_reachable_score(board: Board, piece: Piece) -> float:
    """Best 1-ply score obtainable by placing ``piece`` anywhere on ``board`` —
    the second ply of the lookahead. A large penalty means it can't be placed
    (a top-out), which the lookahead should avoid."""
    base = board.snapshot()
    best = None
    for rot in range(4):
        shape = SHAPES[piece.name][rot]
        min_x = min(c[0] for c in shape)
        max_x = max(c[0] for c in shape)
        for px in range(-min_x, COLS - max_x):
            py = board.drop_py(piece, rot, px)
            cells = piece.cells(rot, px, py)
            if board.collides(cells) or any(y < 0 for (_, y) in cells):
                continue
            lines, grid = _drop_and_clear(base, piece, rot, px, py)
            s = W_LINES * lines + _static_eval(grid)[0]
            if best is None or s > best:
                best = s
    return best if best is not None else -1e9


def compute_lookahead(board: Board, piece: Piece, placements: List[Placement],
                      next_name) -> List[Placement]:
    """Fill each placement's 2-ply ``lookahead``: the immediate line reward plus
    the best score reachable by then placing the next piece. This makes the AI
    set up clears with the current piece. With no known next piece, ``lookahead``
    stays equal to the 1-ply score."""
    if not next_name or next_name not in SHAPES or not placements:
        return placements
    next_piece = Piece(next_name)
    base = board.snapshot()
    for pl in placements:
        _, grid = _drop_and_clear(base, piece, pl.rot, pl.px, pl.py)
        nxt = Board()
        nxt.grid = grid
        pl.lookahead = W_LINES * pl.lines + _best_reachable_score(nxt, next_piece)
    return placements


def best_placement(placements: List[Placement]) -> Placement | None:
    """Best placement by 2-ply lookahead (equals the 1-ply score until
    ``compute_lookahead`` has been run)."""
    if not placements:
        return None
    return max(placements, key=lambda p: p.lookahead)
