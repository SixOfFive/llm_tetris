"""The playfield grid and all stack mutations (lock, line clear, garbage)."""

from __future__ import annotations

from typing import List, Tuple

from .constants import COLS, ROWS
from .pieces import Cell, Piece

EMPTY = 0
GARBAGE = "G"


class Board:
    def __init__(self):
        # grid[row][col]; row 0 is the top. EMPTY (0) or a cell key string.
        self.grid: List[List] = [[EMPTY] * COLS for _ in range(ROWS)]

    # -- queries ------------------------------------------------------------
    def cell_blocked(self, x: int, y: int) -> bool:
        """True if cell (x, y) is outside the walls/floor or already filled.

        Cells above the ceiling (y < 0) are treated as open sky so a piece may
        sit or rotate partly above the field.
        """
        if x < 0 or x >= COLS or y >= ROWS:
            return True
        if y < 0:
            return False
        return self.grid[y][x] != EMPTY

    def collides(self, cells: List[Cell]) -> bool:
        return any(self.cell_blocked(x, y) for (x, y) in cells)

    def piece_fits(self, piece: Piece, rot: int, px: int, py: int) -> bool:
        return not self.collides(piece.cells(rot, px, py))

    def drop_py(self, piece: Piece, rot: int, px: int) -> int:
        """Final ``py`` for a hard drop of ``piece`` at rotation/column."""
        py = piece.py
        # Raise until it fits (handles spawning into garbage), then fall.
        while self.collides(piece.cells(rot, px, py)) and py > -4:
            py -= 1
        while not self.collides(piece.cells(rot, px, py + 1)):
            py += 1
        return py

    # -- mutations ----------------------------------------------------------
    def lock(self, piece: Piece, rot: int, px: int, py: int) -> bool:
        """Write the piece into the grid.

        Returns ``True`` on a *lock-out* (a cell came to rest above the
        ceiling), which the caller treats as a game-over.
        """
        locked_out = False
        for (x, y) in piece.cells(rot, px, py):
            if y < 0:
                locked_out = True
                continue
            if 0 <= x < COLS and 0 <= y < ROWS:
                self.grid[y][x] = piece.name
        return locked_out

    def clear_full_rows(self) -> int:
        """Remove completed rows, dropping the stack down. Returns count."""
        kept = [row for row in self.grid if any(c == EMPTY for c in row)]
        cleared = ROWS - len(kept)
        if cleared:
            new_rows = [[EMPTY] * COLS for _ in range(cleared)]
            self.grid = new_rows + kept
        return cleared

    def add_garbage(self, lines: int, gap_col: int) -> bool:
        """Insert ``lines`` garbage rows at the bottom, each with one open
        column ``gap_col``.  The existing stack is shoved up by ``lines``.

        Returns ``True`` if filled cells were pushed above the ceiling
        (a top-out caused by garbage).
        """
        if lines <= 0:
            return False
        gap_col = max(0, min(COLS - 1, gap_col))
        # Rows that fall off the top carry a top-out if any were occupied.
        pushed_off = self.grid[:lines]
        topped_out = any(c != EMPTY for row in pushed_off for c in row)

        garbage_row = lambda: [(EMPTY if c == gap_col else GARBAGE) for c in range(COLS)]
        self.grid = self.grid[lines:] + [garbage_row() for _ in range(lines)]
        return topped_out

    # -- metrics (used by the heuristic AI / LLM prompt) --------------------
    def column_heights(self) -> List[int]:
        heights = [0] * COLS
        for x in range(COLS):
            for y in range(ROWS):
                if self.grid[y][x] != EMPTY:
                    heights[x] = ROWS - y
                    break
        return heights

    def count_holes(self) -> int:
        """Empty cells that have at least one filled cell somewhere above."""
        holes = 0
        for x in range(COLS):
            seen_block = False
            for y in range(ROWS):
                if self.grid[y][x] != EMPTY:
                    seen_block = True
                elif seen_block:
                    holes += 1
        return holes

    def snapshot(self) -> List[List]:
        return [row[:] for row in self.grid]
