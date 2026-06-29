"""Entry point and game loop: human (left) vs LLM (right)."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

import pygame

from . import constants as C
from .ai import best_placement, enumerate_placements
from .board import Board
from .game import Game
from .llm_player import LLMClient
from .pieces import SPAWN_Y, Piece

DAS_DELAY = 150     # ms before auto-repeat kicks in
ARR = 40            # ms between auto-repeat moves

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config() -> dict:
    # Prefer the local config.json (git-ignored); fall back to the committed
    # example so a fresh clone still runs.
    cfg = {"llm": {}, "game": {}}
    for fname in ("config.json", "config.example.json"):
        path = os.path.join(ROOT, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                cfg.update(loaded)
                break
            print(f"[config] ignoring non-object config root in {fname} ({type(loaded).__name__})")
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
            print(f"[config] {fname} unreadable, trying fallback ({exc})")
    game = dict(C.DEFAULTS)
    game.update(cfg.get("game") or {})
    cfg["game"] = game
    cfg["llm"] = cfg.get("llm") or {}
    return cfg


class LLMController:
    """Drives the LLM board as a *pipeline*.

    The LLM is slow (a few seconds per reply), so we never let its piece sit
    frozen "thinking".  Instead:

      * When a piece spawns we already have its decision (pre-fetched during the
        previous piece's animation), so the program immediately rotates, shifts
        and lowers it into place tick-by-tick — it looks like the model is
        playing in real time.
      * The instant we start animating, we fire the LLM request for the *next*
        piece, computed on the board as it will look after the current piece
        lands (a genuine one-piece lookahead).  Its 2-9 s of thinking overlaps
        the animation, so by the next spawn the answer is usually ready.

    Only the very first piece, or a spawn where the predicted board diverged
    (e.g. surprise garbage), shows a brief "Thinking…".  If a pre-fetched move
    is no longer legal on the real board, we fall back to the heuristic best
    move instantly rather than stalling.
    """

    MIN_STEP_MS = 22            # fastest a single rotate/shift/drop step may go
    MAX_STEP_MS = 240           # slowest, so motion never looks frozen between steps

    def __init__(self, client: LLMClient, cfg_game: dict):
        self.client = client
        self.min_step_ms = cfg_game.get("llm_anim_min_step_ms", self.MIN_STEP_MS)
        self.max_step_ms = cfg_game.get("llm_anim_max_step_ms", self.MAX_STEP_MS)
        # Tempo matching: place a piece on a cadence tied to how fast the human
        # is dropping pieces — slightly faster (speed_factor > 1) so the AI keeps
        # its board clean, but never faster than the model can actually answer.
        self.speed_factor = cfg_game.get("llm_speed_factor", 1.15)
        self.max_cadence_ms = cfg_game.get("llm_max_cadence_ms", 6000)
        self.status = "—"
        self.log: list[str] = []
        self.llm_active = bool(client.enabled and client.base_url)
        self.recent_latency_s = 2.0 if self.llm_active else 0.5
        self.human_spp_ms = 1800.0  # human seconds-per-piece estimate (updated live)
        self._has_human = False
        self.cadence_ms = 1800.0
        self.anim_step_ms = self.max_step_ms
        self._reset_turn()
        self.pending = False        # is an LLM request in flight / awaiting consume?
        self.pending_result = None  # its MoveResult once polled

    def _reset_turn(self):
        self.decided = None         # dict(placement, reason, source, latency) for llm.current
        self.anim_phase = None      # 'rotate' | 'shift' | 'descend' | 'settle'
        self.anim_t = 0.0
        self.anim_elapsed = 0.0     # total time since this piece began animating

    def _log_move(self, piece, placement, source, reason, latency):
        if placement is None:
            self.log.append(f"{piece}  ->  no legal placement  ({source})")
        else:
            tag = f"{source}, {latency:.1f}s" if latency else source
            self.log.append(
                f"{piece}  ->  rot {placement.rot}, col {placement.px}   "
                f"clears {placement.lines}   ({tag})"
            )
            if reason:
                self.log.append(f"· {reason}")
        self.log = self.log[-60:]

    # -- decision resolution ------------------------------------------------
    def _resolve_real(self, mr, llm):
        """Map an LLM reply (possibly computed on a predicted board) onto the
        real current board, by matching (rotation, column).  Falls back to the
        heuristic best move if the chosen placement is no longer legal."""
        placements = enumerate_placements(llm.board, llm.current)
        chosen, source, reason = None, mr.source, mr.reason
        if mr.placement is not None:
            want = (mr.placement.rot, mr.placement.px)
            chosen = next((p for p in placements if (p.rot, p.px) == want), None)
        if chosen is None:
            chosen = best_placement(placements)
            if mr.placement is not None:           # had a pick, but it went stale
                source = "fallback"
                reason = f"(lookahead stale) {reason}".strip()
        return {"placement": chosen, "reason": reason, "source": source,
                "latency": mr.latency}

    def _fire_prefetch(self, llm):
        """Request the NEXT piece's move on the board as it will look once the
        current (already-decided) piece lands and pending garbage is applied."""
        if llm.next_name is None or llm.current is None:
            self.pending = False
            return
        sim = Board()
        sim.grid = [row[:] for row in llm.board.grid]
        tp = self.decided["placement"]
        if tp is not None:
            for (x, y) in llm.current.cells(tp.rot, tp.px, tp.py):
                if 0 <= y < C.ROWS and 0 <= x < C.COLS:
                    sim.grid[y][x] = llm.current.name
            sim.clear_full_rows()
        for lines, gap in llm.incoming:            # garbage applied before next spawn
            sim.add_garbage(lines, gap)
        self.client.request_move(sim, Piece(llm.next_name), "?", llm.incoming_count())
        self.pending = True
        self.pending_result = None

    # -- per-frame ----------------------------------------------------------
    def update(self, dt, llm: Game, player: Game, on_lock, human_spp_ms=None):
        if human_spp_ms:
            self.human_spp_ms = human_spp_ms
            self._has_human = True
        if llm.dead or llm.current is None:
            self.status = "—"
            return

        if self.decided is None:
            self._acquire_decision(dt, llm)
        else:
            # keep draining the look-ahead request while we animate
            if self.pending and self.pending_result is None:
                self.pending_result = self.client.poll()
            self._animate(dt, llm, player, on_lock)

    def _acquire_decision(self, dt, llm):
        if not self.pending:
            # no look-ahead in flight (first piece, or after a stall) -> ask now
            self.client.request_move(llm.board, llm.current, llm.next_name,
                                     llm.incoming_count())
            self.pending = True
            self.pending_result = None
        if self.pending_result is None:
            self.pending_result = self.client.poll()

        if self.pending_result is None:
            self.status = f"Thinking about {llm.current.name}…"
            return

        # We have a reply for this piece.
        self.decided = self._resolve_real(self.pending_result, llm)
        self._log_move(llm.current.name, self.decided["placement"],
                       self.decided["source"], self.decided["reason"],
                       self.decided["latency"])
        self.pending = False
        self.pending_result = None
        if llm.current is not None:
            llm.current.py = SPAWN_Y
        self.anim_phase = "rotate"
        self.anim_t = 0.0
        self._plan_pacing(llm)          # stretch the animation to ~cover the next think
        self._fire_prefetch(llm)        # start thinking about the next piece now

    def _plan_pacing(self, llm):
        """Pick this piece's cadence (time until it locks) and the per-step
        animation speed.

        Target cadence = the human's seconds-per-piece divided by the speed
        factor (so the AI is a touch faster and keeps its board clean), but
        never shorter than the model can answer in, and never longer than the
        cap.  The animation is then spread across that cadence; if it finishes
        early the piece "settles" at the bottom until the cadence is up.
        """
        tp = self.decided["placement"]
        p = llm.current
        lat = self.decided["latency"]
        if self.decided["source"] == "llm" and lat and lat > 0:
            self.recent_latency_s = 0.6 * self.recent_latency_s + 0.4 * lat

        # Floor: we must have the *next* decision ready by the time we lock.
        floor = (self.recent_latency_s * 1000.0 + 150.0) if self.llm_active else 250.0
        desired = (self.human_spp_ms / self.speed_factor) if self.human_spp_ms else floor
        self.cadence_ms = max(floor, min(self.max_cadence_ms, desired))

        if tp is None or p is None:
            self.anim_step_ms = self.max_step_ms
            return
        steps = (tp.rot - p.rot) % 4 + abs(tp.px - p.px) + max(0, tp.py - p.py)
        steps = max(1, steps)
        self.anim_step_ms = max(self.min_step_ms, min(self.max_step_ms, self.cadence_ms / steps))

    def _human_pace_note(self):
        cad = self.cadence_ms / 1000.0
        if self._has_human:
            return f"you ~{self.human_spp_ms / 1000.0:.1f}s/pc · AI {cad:.1f}s/pc"
        return f"pace {cad:.1f}s/pc"

    def _animate(self, dt, llm, player, on_lock):
        tp = self.decided["placement"]
        nxt = llm.next_name or "?"
        self.status = (f"Placing {llm.current.name} -> looking ahead to {nxt}"
                       f"   ({self._human_pace_note()})")
        if tp is None:                              # nothing legal -> drop & top out
            res = llm.hard_drop()
            on_lock(llm, player, res)
            self._finish_turn(llm)
            return

        self.anim_elapsed += dt
        self.anim_t += dt
        step = self.anim_step_ms
        while self.anim_t >= step and self.anim_phase != "settle":
            self.anim_t -= step
            p = llm.current
            if p is None:
                break
            if self.anim_phase == "rotate":
                if p.rot != tp.rot:
                    p.rot = (p.rot + 1) % 4
                else:
                    self.anim_phase = "shift"
            elif self.anim_phase == "shift":
                if p.px < tp.px:
                    p.px += 1
                elif p.px > tp.px:
                    p.px -= 1
                else:
                    self.anim_phase = "descend"
            elif self.anim_phase == "descend":
                if p.py < tp.py:
                    p.py += 1
                else:
                    p.rot, p.px = tp.rot, tp.px
                    self.anim_phase = "settle"   # rest at the bottom on cadence

        # Lock once the piece is home AND the full cadence has elapsed, so the
        # AI never outruns the human's tempo (and the next decision is ready).
        if self.anim_phase == "settle" and self.anim_elapsed >= self.cadence_ms:
            res = llm.hard_drop()
            on_lock(llm, player, res)
            self._finish_turn(llm)

    def _finish_turn(self, llm: Game):
        llm.spawn()
        self._reset_turn()
        # self.pending / pending_result hold the look-ahead for the new piece.


class BattleTetris:
    def __init__(self, cfg, no_llm=False, start_paused=True):
        self.cfg = cfg
        self.start_paused = start_paused
        seed = cfg["game"].get("seed")
        self.rng = random.Random(seed) if seed is not None else random.Random()

        llm_cfg = dict(cfg.get("llm", {}))
        if no_llm:
            llm_cfg["enabled"] = False
        gm = cfg["game"]["garbage_multiplier"]
        # Two clients: the right board always; the left board only in LLM-vs-LLM
        # mode (a separate client so their requests never clobber each other).
        self.client = LLMClient(llm_cfg, garbage_multiplier=gm)
        self.client_left = LLMClient(llm_cfg, garbage_multiplier=gm)
        base_name = llm_cfg.get("model", "LLM") if not no_llm else "Heuristic AI"
        self.model_name = base_name
        self.vs_mode = "human"          # "human" | "ai"
        self._left_warmed = False

        pygame.init()
        pygame.display.set_caption("Tetris Duel  ·  You vs LLM")
        self.screen = pygame.display.set_mode((C.WINDOW_W, C.WINDOW_H))
        self.clock = pygame.time.Clock()

        from .assets import Assets
        from .renderer import Renderer
        self.assets = Assets()
        self.renderer = Renderer(self.screen, self.assets)

        self.reset()
        self.client.warmup()

    def reset(self):
        g = self.cfg["game"]
        self.player = Game(self.rng, g["player_gravity_ms"], g["lock_delay_ms"],
                           g["garbage_multiplier"])
        self.player.soft_drop_ms = g["soft_drop_ms"]
        self.llm = Game(self.rng, g["player_gravity_ms"], g["lock_delay_ms"],
                        g["garbage_multiplier"])
        self.player.start()
        self.llm.start()
        self.controller = LLMController(self.client, g)
        self.controller_left = (LLMController(self.client_left, g)
                                if self.vs_mode == "ai" else None)
        self.state = "paused" if self.start_paused else "playing"   # playing | paused | over
        self.winner = None
        self.move_dir = 0
        self.das_t = 0.0
        self.das_charged = False
        # human tempo tracking (seconds-per-piece) so the AI can match it
        self.elapsed_ms = 0.0
        self.last_player_lock_ms = None
        self.human_spp_ms = 1800.0

    @staticmethod
    def on_lock(src: Game, dst: Game, res):
        if res and res.attack > 0:
            dst.receive_garbage(res.attack)

    def _record_player_lock(self):
        """Update the rolling estimate of how fast the human drops pieces."""
        if self.last_player_lock_ms is not None:
            interval = self.elapsed_ms - self.last_player_lock_ms
            if 120.0 < interval < 15000.0:          # ignore absurd gaps (idle/pause)
                self.human_spp_ms = 0.5 * self.human_spp_ms + 0.5 * interval
        self.last_player_lock_ms = self.elapsed_ms

    # -- input --------------------------------------------------------------
    def handle_key(self, key):
        if key == pygame.K_ESCAPE:
            return False
        if key in (pygame.K_p,) and self.state in ("playing", "paused"):
            self.state = "paused" if self.state == "playing" else "playing"
            return True
        if key == pygame.K_r:
            self.reset()
            return True
        if key == pygame.K_l and self.state == "paused":
            # toggle Human-vs-LLM / LLM-vs-LLM at the paused screen
            self.vs_mode = "ai" if self.vs_mode == "human" else "human"
            self.reset()
            if self.vs_mode == "ai" and not self._left_warmed:
                self.client_left.warmup()
                self._left_warmed = True
            return True
        if self.state != "playing" or self.player.dead:
            return True
        if self.vs_mode == "ai":
            return True             # no keyboard control in LLM vs LLM

        if key == pygame.K_LEFT:
            self.player.move(-1)
            self.move_dir = -1
            self.das_t = 0.0
            self.das_charged = False
        elif key == pygame.K_RIGHT:
            self.player.move(1)
            self.move_dir = 1
            self.das_t = 0.0
            self.das_charged = False
        elif key in (pygame.K_UP, pygame.K_x):
            self.player.rotate(cw=True)
        elif key in (pygame.K_z, pygame.K_LCTRL, pygame.K_RCTRL):
            self.player.rotate(cw=False)
        elif key == pygame.K_SPACE:
            res = self.player.hard_drop()
            if res:
                self.on_lock(self.player, self.llm, res)
                self._record_player_lock()
                self.player.spawn()
        return True

    def handle_keyup(self, key):
        if key == pygame.K_LEFT and self.move_dir == -1:
            self.move_dir = 0
        elif key == pygame.K_RIGHT and self.move_dir == 1:
            self.move_dir = 0

    def _das(self, dt):
        if self.move_dir == 0 or self.state != "playing":
            return
        self.das_t += dt
        if not self.das_charged:
            if self.das_t >= DAS_DELAY:
                self.das_charged = True
                self.das_t = 0.0
                self.player.move(self.move_dir)
        else:
            while self.das_t >= ARR:
                self.das_t -= ARR
                self.player.move(self.move_dir)

    # -- main loop ----------------------------------------------------------
    def step(self, dt):
        if self.state != "playing":
            return
        self.elapsed_ms += dt

        if self.vs_mode == "ai":
            # both boards LLM-driven; neither tempo-matches a human
            self.controller_left.update(dt, self.player, self.llm, self.on_lock)
            self.controller.update(dt, self.llm, self.player, self.on_lock)
        else:
            keys = pygame.key.get_pressed()
            soft = keys[pygame.K_DOWN]
            self._das(dt)
            res = self.player.update(dt, soft)
            if res is not None:
                self.on_lock(self.player, self.llm, res)
                self._record_player_lock()
                self.player.spawn()
            self.controller.update(dt, self.llm, self.player, self.on_lock,
                                   human_spp_ms=self.human_spp_ms)

        if self.player.dead or self.llm.dead:
            self.state = "over"
            self.winner = "llm" if self.player.dead else "player"

    def render(self):
        if self.vs_mode == "ai":
            player_label = f"{self.model_name}  (A)"
            right_label = f"{self.model_name}  (B)"
            left_status = self.controller_left.status if self.controller_left else "—"
            left_log = self.controller_left.log if self.controller_left else []
            mode_label = "Mode: LLM vs LLM"
        else:
            player_label = "YOU"
            right_label = self.model_name
            left_status = None
            left_log = None
            mode_label = "Mode: Human vs LLM"
        self.renderer.render(
            self.player, self.llm,
            llm_status=self.controller.status,
            llm_log=self.controller.log,
            winner=self.winner,
            state=self.state,
            model_name=right_label,
            player_label=player_label,
            left_status=left_status,
            left_log=left_log,
            mode_label=mode_label,
        )
        pygame.display.flip()

    def run(self, max_frames: int | None = None):
        running = True
        frames = 0
        try:
            while running:
                dt = self.clock.tick(C.FPS)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        running = self.handle_key(event.key)
                    elif event.type == pygame.KEYUP:
                        self.handle_keyup(event.key)
                self.step(dt)
                self.render()
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    running = False
        finally:
            self.client.shutdown()
            self.client_left.shutdown()
            pygame.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tetris Duel: You vs an LLM.")
    parser.add_argument("--no-llm", action="store_true",
                        help="disable the network LLM; the heuristic AI plays instead")
    parser.add_argument("--regen-assets", action="store_true",
                        help="regenerate image assets before starting")
    parser.add_argument("--frames", type=int, default=None,
                        help="run N frames then exit (headless self-test)")
    args = parser.parse_args(argv)

    if args.regen_assets:
        from generate_assets import ensure_assets
        ensure_assets(force=True)

    cfg = load_config()
    game = BattleTetris(cfg, no_llm=args.no_llm)
    game.run(max_frames=args.frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
