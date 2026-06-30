"""Per-side game state: active piece, gravity, lock delay, garbage queue.

One ``Game`` instance drives each side.  The human side is advanced with
``update()`` (gravity + lock delay) and steered by keyboard handlers.  The LLM
side reuses the same mechanics but is steered move-by-move from the main loop,
so its ``update()`` is never called for gravity.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .board import Board
from .constants import COLS
from .pieces import BagRandomizer, Piece, kick_offsets


@dataclass
class LockResult:
    lines: int          # lines cleared by this lock
    attack: int         # garbage lines to send to the opponent
    topped_out: bool    # did this lock end the game for this side


class Game:
    def __init__(self, rng: random.Random, gravity_ms: int, lock_delay_ms: int,
                 garbage_multiplier: int = 2):
        self.rng = rng
        self.board = Board()
        self.gravity_ms = gravity_ms
        self.soft_drop_ms = 40
        self.lock_delay_ms = lock_delay_ms
        self.garbage_multiplier = garbage_multiplier

        self.bag = BagRandomizer(rng)
        self.current: Optional[Piece] = None
        self.next_name: str = self.bag.next()        # the upcoming piece
        self.next_next_name: str = self.bag.next()   # the one after (for 2-ply lookahead)
        self.dead = False

        self.lines_cleared = 0
        self.lines_sent = 0
        self.pieces_placed = 0

        # incoming garbage: list of (line_count, gap_column) batches
        self.incoming: List[Tuple[int, int]] = []

        self._fall_acc = 0.0
        self._lock_acc = 0.0

    # -- setup --------------------------------------------------------------
    def start(self):
        self.spawn()

    # -- garbage ------------------------------------------------------------
    def receive_garbage(self, lines: int):
        if lines <= 0:
            return
        gap = self.rng.randrange(COLS)
        self.incoming.append((lines, gap))

    def incoming_count(self) -> int:
        return sum(n for n, _ in self.incoming)

    def _apply_incoming(self) -> bool:
        topped = False
        for lines, gap in self.incoming:
            if self.board.add_garbage(lines, gap):
                topped = True
        self.incoming.clear()
        return topped

    # -- piece lifecycle ----------------------------------------------------
    def spawn(self):
        """Apply queued garbage, then bring in the next piece."""
        if self.dead:
            return
        if self._apply_incoming():
            self.dead = True
            self.current = None
            return
        piece = Piece(self.next_name)
        self.next_name = self.next_next_name
        self.next_next_name = self.bag.next()
        self._fall_acc = 0.0
        self._lock_acc = 0.0
        if self.board.collides(piece.cells()):
            self.dead = True
            self.current = None
            return
        self.current = piece

    def _touch(self):
        """Reset lock delay after a successful move/rotation while grounded."""
        if self.current and not self.board.piece_fits(
            self.current, self.current.rot, self.current.px, self.current.py + 1
        ):
            self._lock_acc = 0.0

    # -- inputs (human) -----------------------------------------------------
    def move(self, dx: int) -> bool:
        if self.current is None or self.dead:
            return False
        p = self.current
        if self.board.piece_fits(p, p.rot, p.px + dx, p.py):
            p.px += dx
            self._touch()
            return True
        return False

    def rotate(self, cw: bool = True) -> bool:
        if self.current is None or self.dead:
            return False
        p = self.current
        to = (p.rot + (1 if cw else -1)) % 4
        for dx, dy in kick_offsets(p.name, p.rot, to):
            if self.board.piece_fits(p, to, p.px + dx, p.py + dy):
                p.rot, p.px, p.py = to, p.px + dx, p.py + dy
                self._touch()
                return True
        return False

    def ghost_py(self) -> int:
        p = self.current
        return self.board.drop_py(p, p.rot, p.px)

    def hard_drop(self) -> Optional[LockResult]:
        if self.current is None or self.dead:
            return None
        p = self.current
        p.py = self.board.drop_py(p, p.rot, p.px)
        return self._lock()

    # -- gravity (human side) ----------------------------------------------
    def update(self, dt_ms: float, soft_drop: bool) -> Optional[LockResult]:
        if self.current is None or self.dead:
            return None
        p = self.current
        eff = self.soft_drop_ms if soft_drop else self.gravity_ms
        self._fall_acc += dt_ms
        moved = False
        while self._fall_acc >= eff:
            self._fall_acc -= eff
            if self.board.piece_fits(p, p.rot, p.px, p.py + 1):
                p.py += 1
                moved = True
            else:
                self._fall_acc = 0.0
                break
        if moved:
            self._lock_acc = 0.0

        grounded = not self.board.piece_fits(p, p.rot, p.px, p.py + 1)
        if grounded:
            self._lock_acc += dt_ms
            if self._lock_acc >= self.lock_delay_ms:
                return self._lock()
        else:
            self._lock_acc = 0.0
        return None

    # -- locking ------------------------------------------------------------
    def _lock(self) -> LockResult:
        p = self.current
        topped = self.board.lock(p, p.rot, p.px, p.py)
        lines = self.board.clear_full_rows()
        self.lines_cleared += lines
        self.pieces_placed += 1
        attack = lines * self.garbage_multiplier if lines > 0 else 0
        self.lines_sent += attack
        self.current = None
        if topped:
            self.dead = True
        return LockResult(lines=lines, attack=attack, topped_out=topped)
