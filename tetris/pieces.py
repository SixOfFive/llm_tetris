"""Tetromino definitions, SRS rotation states and wall-kick tables.

Coordinate system: each rotation state is a list of four ``(x, y)`` cells
inside the piece's local bounding box, with ``x`` increasing to the right and
``y`` increasing downward (matching screen/grid orientation).  A live piece has
an absolute box origin ``(px, py)``; an occupied grid cell is ``(px + x,
py + y)``.

The four rotation indices are ``0`` (spawn), ``1`` (clockwise / "R"),
``2`` (180) and ``3`` (counter-clockwise / "L").
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

Cell = Tuple[int, int]

# ---------------------------------------------------------------------------
# SRS rotation states.  JLSTZ/T live in a 3x3 box, I and O in a 4x4 box.
# ---------------------------------------------------------------------------
SHAPES: Dict[str, List[List[Cell]]] = {
    "I": [
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        [(2, 0), (2, 1), (2, 2), (2, 3)],
        [(0, 2), (1, 2), (2, 2), (3, 2)],
        [(1, 0), (1, 1), (1, 2), (1, 3)],
    ],
    "O": [
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
    ],
    "T": [
        [(1, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "S": [
        [(1, 0), (2, 0), (0, 1), (1, 1)],
        [(1, 0), (1, 1), (2, 1), (2, 2)],
        [(1, 1), (2, 1), (0, 2), (1, 2)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "Z": [
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(2, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(1, 0), (0, 1), (1, 1), (0, 2)],
    ],
    "J": [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    "L": [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
}

# Spawn box origin: all pieces spawn with box-left at column 3, top row 0.
SPAWN_X = 3
SPAWN_Y = 0

# ---------------------------------------------------------------------------
# Wall-kick tables, expressed in this module's y-down coordinates.
# Keyed by (from_rotation, to_rotation) -> list of (dx, dy) offsets tried in
# order; the first offset that yields a collision-free placement wins.
# ---------------------------------------------------------------------------
KICKS_JLSTZ: Dict[Tuple[int, int], List[Cell]] = {
    (0, 1): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (1, 0): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    (1, 2): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    (2, 1): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (2, 3): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
    (3, 2): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (3, 0): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (0, 3): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
}

KICKS_I: Dict[Tuple[int, int], List[Cell]] = {
    (0, 1): [(0, 0), (-2, 0), (1, 0), (-2, 1), (1, -2)],
    (1, 0): [(0, 0), (2, 0), (-1, 0), (2, -1), (-1, 2)],
    (1, 2): [(0, 0), (-1, 0), (2, 0), (-1, -2), (2, 1)],
    (2, 1): [(0, 0), (1, 0), (-2, 0), (1, 2), (-2, -1)],
    (2, 3): [(0, 0), (2, 0), (-1, 0), (2, -1), (-1, 2)],
    (3, 2): [(0, 0), (-2, 0), (1, 0), (-2, 1), (1, -2)],
    (3, 0): [(0, 0), (1, 0), (-2, 0), (1, 2), (-2, -1)],
    (0, 3): [(0, 0), (-1, 0), (2, 0), (-1, -2), (2, 1)],
}


def kick_offsets(name: str, frm: int, to: int) -> List[Cell]:
    """Return the wall-kick offsets for a rotation transition."""
    if name == "O":
        return [(0, 0)]
    table = KICKS_I if name == "I" else KICKS_JLSTZ
    return table.get((frm, to), [(0, 0)])


class Piece:
    """A live tetromino: a name, a rotation index and a box origin."""

    __slots__ = ("name", "rot", "px", "py")

    def __init__(self, name: str, rot: int = 0, px: int = SPAWN_X, py: int = SPAWN_Y):
        self.name = name
        self.rot = rot % 4
        self.px = px
        self.py = py

    def clone(self) -> "Piece":
        return Piece(self.name, self.rot, self.px, self.py)

    def cells(self, rot: int | None = None, px: int | None = None, py: int | None = None) -> List[Cell]:
        """Absolute grid cells for this piece (optionally overriding fields)."""
        r = self.rot if rot is None else rot % 4
        ox = self.px if px is None else px
        oy = self.py if py is None else py
        return [(ox + x, oy + y) for (x, y) in SHAPES[self.name][r]]

    @property
    def color(self):
        from .constants import COLORS
        return COLORS[self.name]


class BagRandomizer:
    """Standard 7-bag: each cycle yields the seven pieces in random order."""

    def __init__(self, rng: random.Random):
        self._rng = rng
        self._bag: List[str] = []

    def _refill(self):
        bag = list(SHAPES.keys())
        self._rng.shuffle(bag)
        self._bag = bag

    def next(self) -> str:
        if not self._bag:
            self._refill()
        return self._bag.pop()
