"""LLM opponent: builds the prompt, calls the InfiniteModel / OpenAI-compatible
gateway off the main thread, and resolves the reply into a concrete move.

The gateway at ``base_url`` speaks the OpenAI ``/chat/completions`` dialect.
``qwen3:4b`` is a hybrid-reasoning model, so we append Qwen's ``/no_think``
switch and additionally strip any ``<think>...</think>`` block before parsing.
If anything goes wrong (timeout, bad JSON, illegal id) we fall back to the
heuristic best placement so the AI side always keeps playing.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional

import requests

from .ai import Placement, best_placement, enumerate_placements
from .board import Board, EMPTY, GARBAGE
from .constants import COLS, ROWS
from .pieces import Piece

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
MENU_LIMIT = 14


@dataclass
class MoveResult:
    placement: Placement
    reason: str
    source: str        # "llm" | "fallback" | "error"
    raw: str
    latency: float


def _ascii_board(board: Board) -> str:
    rows = []
    for row in board.grid:
        rows.append("".join("." if c == EMPTY else ("o" if c == GARBAGE else "#") for c in row))
    return "\n".join(rows)


class LLMClient:
    def __init__(self, cfg: dict, garbage_multiplier: int = 2):
        self.cfg = cfg
        self.enabled = cfg.get("enabled", True)
        self.base_url = cfg.get("base_url", "").rstrip("/")
        self.model = cfg.get("model", "qwen3:4b")
        self.api_key = cfg.get("api_key", "not-needed")
        self.temperature = cfg.get("temperature", 0.2)
        self.max_tokens = cfg.get("max_tokens", 220)
        self.timeout = cfg.get("timeout_seconds", 12.0)
        self.disable_thinking = cfg.get("disable_thinking", True)
        self.garbage_multiplier = garbage_multiplier
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm")
        self._future: Optional[Future] = None

    # -- lifecycle ----------------------------------------------------------
    def warmup(self):
        """Fire a tiny request so the model is resident before the first turn."""
        if not (self.enabled and self.base_url):
            return
        self._pool.submit(self._safe_chat, "Reply with the word ready.", "", 8)

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- async move request -------------------------------------------------
    def is_busy(self) -> bool:
        return self._future is not None and not self._future.done()

    def request_move(self, board: Board, piece: Piece, next_name: str, incoming: int):
        """Begin computing a move for ``piece`` on ``board`` (non-blocking)."""
        placements = enumerate_placements(board, piece)
        self._future = self._pool.submit(
            self._compute, board, piece, next_name, incoming, placements
        )

    def poll(self) -> Optional[MoveResult]:
        """Return the MoveResult once ready, else ``None``. Consumes it."""
        if self._future is None or not self._future.done():
            return None
        try:
            result = self._future.result()
        except Exception as exc:  # pragma: no cover - defensive
            result = MoveResult(
                placement=None, reason=f"error: {exc}", source="error", raw=str(exc), latency=0.0
            )
        self._future = None
        return result

    # -- internals ----------------------------------------------------------
    def _compute(self, board, piece, next_name, incoming, placements) -> MoveResult:
        fallback = best_placement(placements)
        if not placements:
            return MoveResult(fallback, "no legal move", "fallback", "", 0.0)

        if not (self.enabled and self.base_url):
            return MoveResult(fallback, "heuristic (LLM off)", "fallback", "", 0.0)

        # Present only the strongest options, ranked best-first and numbered
        # 0..N.  Even a tiny model that just blurts a small number then lands on
        # a good move, while a capable model can still weigh the outcomes.
        menu = sorted(placements, key=lambda p: p.score, reverse=True)[:MENU_LIMIT]
        system, user = self._build_prompt(board, piece, next_name, incoming, menu)
        t0 = time.monotonic()
        try:
            raw = self._safe_chat(system, user, self.max_tokens)
        except Exception as exc:
            return MoveResult(fallback, f"heuristic (LLM error: {exc})", "fallback", str(exc),
                              time.monotonic() - t0)
        latency = time.monotonic() - t0

        chosen, reason = self._parse(raw, menu)
        if chosen is None:
            return MoveResult(fallback, f"heuristic (bad reply) {reason}".strip(), "fallback",
                              raw, latency)
        if not reason:                      # small models often pick an id with no words
            reason = (f"clears {chosen.lines}, holes {chosen.holes_after}, "
                      f"max-h {chosen.max_height}")
        return MoveResult(chosen, reason, "llm", raw, latency)

    def _build_prompt(self, board, piece, next_name, incoming, menu):
        mult = self.garbage_multiplier
        suffix = " /no_think" if self.disable_thinking else ""
        attack_rule = ""
        if mult > 0:
            attack_rule = (
                "ATTACK RULE: when you clear N lines at once, the opponent receives "
                f"N x {mult} garbage lines pushed up from the bottom of THEIR board "
                "(each solid except one gap). Clearing multiple lines at once hits "
                "harder.\n"
            )
        system = (
            "You are an expert Tetris AI. You control the RIGHT board in a duel "
            "against an opponent on the LEFT.\n"
            + attack_rule +
            "SURVIVAL RULE: if your stack reaches the top you LOSE. Holes (empty "
            "cells trapped under blocks) are very hard to clear.\n"
            "PRIME DIRECTIVE: CLEAR ROWS and keep your stack LOW. Your #1 job is "
            "to complete and clear rows as often as possible — if any option "
            "clears one or more lines, strongly prefer it (more 'clears' is "
            "better). Keep the overall stack as low as you can; do not build tall "
            "towers, and never bury holes under blocks. (Keeping one column open "
            "to set up a clear is fine — just don't pile up.)\n"
            "You get a numbered MENU of strong placements (best candidates first) "
            "with each option's outcome (clears / holes_after / max_height). "
            "Pick the option that clears the most rows while keeping max_height "
            "low and holes_after at 0.\n"
            'Reply with ONLY one JSON object: {"id": <option number>, "reason": '
            '"<=10 words"}. No other text.' + suffix
        )
        menu_lines = [
            f"{i}: rot {p.rot}, col {p.px} -> clears {p.lines}, "
            f"holes_after {p.holes_after}, max_height {p.max_height}"
            for i, p in enumerate(menu)
        ]
        heights = board.column_heights()
        user = (
            f"Your board (top to bottom), '#'=block 'o'=garbage '.'=empty:\n"
            f"{_ascii_board(board)}\n\n"
            f"Column heights (col 0..9): {heights}\n"
            f"Holes: {board.count_holes()}\n"
            f"Current piece: {piece.name}\n"
            f"Next piece: {next_name}\n"
            f"Garbage queued against you: {incoming} lines\n\n"
            f"MENU (id: placement -> outcome):\n" + "\n".join(menu_lines) + "\n\n"
            "Pick the id that best balances attacking and surviving."
        )
        return system, user

    def _safe_chat(self, system: str, user: str, max_tokens: int) -> str:
        url = f"{self.base_url}/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user or "ping"})
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = requests.post(url, json=body, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""

    def _parse(self, raw: str, menu: List[Placement]):
        """Extract (Placement | None, reason) from a raw model reply.

        ``menu`` is the best-first list shown to the model; the reply's number
        is an index into it.  Tolerant by design: small models often drop the
        JSON wrapper and reply with a bare ``1`` or ``"id": 2``.  We accept a
        JSON object, a bare JSON value, or the first integer in the text.
        """
        text = _THINK_RE.sub("", raw or "").strip()
        by_index = {i: p for i, p in enumerate(menu)}

        obj = None
        m = _JSON_RE.search(text)
        if m:
            try:
                obj = json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                obj = None
        if obj is None:                     # maybe a bare JSON value, e.g. "1"
            try:
                obj = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                obj = None

        if isinstance(obj, dict):
            reason = str(obj.get("reason", "")).strip()[:80]
            if "id" in obj:
                try:
                    idx = int(obj["id"])
                except (TypeError, ValueError):
                    idx = None
                if idx is not None and idx in by_index:
                    return by_index[idx], reason
            if "rotation" in obj and "column" in obj:
                try:
                    rot, col = int(obj["rotation"]) % 4, int(obj["column"])
                except (TypeError, ValueError):
                    rot = col = None
                if rot is not None:
                    for p in menu:
                        if p.rot == rot and p.px == col:
                            return p, reason
        elif isinstance(obj, (int, float)):
            idx = int(obj)
            if idx in by_index:
                return by_index[idx], ""

        # Last resort: first integer anywhere in the cleaned reply.
        mm = re.search(r"-?\d+", text)
        if mm:
            idx = int(mm.group(0))
            if idx in by_index:
                return by_index[idx], ""

        return None, "no usable option"
