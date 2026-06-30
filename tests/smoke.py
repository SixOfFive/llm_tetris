"""Headless logic checks for the Tetris duel. Run:  python tests/smoke.py

Exercises piece geometry, board mechanics, garbage insertion, the placement
enumerator, the LLM reply parser, and a full game loop under SDL's dummy video
driver (no window, no network)."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import random

from tetris.board import Board, EMPTY, GARBAGE
from tetris.constants import COLS, ROWS
from tetris.pieces import SHAPES, Piece, BagRandomizer, kick_offsets
from tetris.ai import enumerate_placements, best_placement
from tetris.game import Game

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}")


def test_shapes():
    for name, rots in SHAPES.items():
        check(f"{name} has 4 rotations", len(rots) == 4)
        for r, cells in enumerate(rots):
            check(f"{name} rot{r} has 4 cells", len(cells) == 4)
            check(f"{name} rot{r} in box", all(0 <= x < 4 and 0 <= y < 4 for x, y in cells))


def test_bag():
    rng = random.Random(1)
    bag = BagRandomizer(rng)
    seen = [bag.next() for _ in range(7)]
    check("7-bag covers all pieces once", sorted(seen) == sorted(SHAPES.keys()))


def test_drop_and_clear():
    b = Board()
    p = Piece("I", rot=0, px=3)
    py = b.drop_py(p, 0, 3)
    cells = p.cells(0, 3, py)
    check("I drops to floor", max(y for _, y in cells) == ROWS - 1)
    # Fill bottom row except one cell, then complete it.
    b = Board()
    for x in range(COLS):
        b.grid[ROWS - 1][x] = "L"
    b.grid[ROWS - 1][5] = EMPTY
    check("row not yet full -> 0 cleared", b.clear_full_rows() == 0)
    b.grid[ROWS - 1][5] = "L"
    check("full row -> 1 cleared", b.clear_full_rows() == 1)
    check("board empty after clear", all(c == EMPTY for row in b.grid for c in row))


def test_garbage():
    b = Board()
    # put a single block on the floor so we can watch it rise
    b.grid[ROWS - 1][0] = "T"
    topped = b.add_garbage(2, gap_col=3)
    check("garbage not a topout here", topped is False)
    check("bottom two rows are garbage rows",
          all(b.grid[ROWS - 1][x] in (GARBAGE, EMPTY) for x in range(COLS)) and
          all(b.grid[ROWS - 2][x] in (GARBAGE, EMPTY) for x in range(COLS)))
    check("gap column 3 is open", b.grid[ROWS - 1][3] == EMPTY and b.grid[ROWS - 2][3] == EMPTY)
    check("gap is the only hole per row",
          sum(1 for x in range(COLS) if b.grid[ROWS - 1][x] == EMPTY) == 1)
    check("original block rose by 2", b.grid[ROWS - 3][0] == "T")

    # topout: fill the very top row then push garbage up
    b2 = Board()
    for x in range(COLS):
        b2.grid[0][x] = "Z"
    check("garbage that pushes filled cells off top -> topout",
          b2.add_garbage(1, gap_col=0) is True)


def test_kicks():
    # every transition table returns exactly 5 offsets (O excluded)
    ok = True
    for name in ("I", "T", "S", "Z", "J", "L"):
        for frm in range(4):
            to = (frm + 1) % 4
            if len(kick_offsets(name, frm, to)) != 5:
                ok = False
    check("kick tables have 5 tests per CW transition", ok)
    check("O has trivial kick", kick_offsets("O", 0, 1) == [(0, 0)])


def test_enumerate():
    b = Board()
    for name in SHAPES:
        pl = enumerate_placements(b, Piece(name))
        check(f"{name}: placements found", len(pl) > 0)
        check(f"{name}: ids unique", len({p.id for p in pl}) == len(pl))
        check(f"{name}: none lock out on empty board",
              all(p.py >= 0 for p in pl))
        # On an empty board nothing clears yet.
        check(f"{name}: best placement exists", best_placement(pl) is not None)
    # I piece flat on the floor should be able to clear a primed row.
    b = Board()
    for x in range(COLS):
        if x not in (3, 4, 5, 6):
            b.grid[ROWS - 1][x] = "L"
    pl = enumerate_placements(b, Piece("I"))
    check("I can complete a primed row", any(p.lines == 1 for p in pl))


def test_parser():
    from tetris.llm_player import LLMClient, MENU_LIMIT
    client = LLMClient({"enabled": False})
    b = Board()
    placements = enumerate_placements(b, Piece("T"))
    menu = sorted(placements, key=lambda p: p.score, reverse=True)[:MENU_LIMIT]
    raw = '<think>\n\n</think>\n\n{"id": 2, "reason": "keep it flat"}'
    chosen, reason = client._parse(raw, menu)
    check("parses id past empty <think> block", chosen is menu[2])
    check("extracts reason", reason == "keep it flat")
    check("bare integer reply maps to menu index", client._parse("1", menu)[0] is menu[1])
    bad = "the answer is probably the second one"
    check("non-number reply rejected", client._parse(bad, menu)[0] is None)
    check("out-of-range id rejected", client._parse('{"id": 9999}', menu)[0] is None)


def test_attack_exchange():
    rng = random.Random(7)
    player = Game(rng, 800, 500)
    llm = Game(rng, 800, 500)
    player.start(); llm.start()
    # Simulate the player clearing 2 lines -> 4 garbage to the LLM.
    from tetris.game import LockResult
    llm.receive_garbage(2 * 2)
    check("llm queued 4 incoming", llm.incoming_count() == 4)
    before = llm.next_name
    llm.spawn()  # applies garbage then spawns
    rows_with_garbage = sum(1 for row in llm.board.grid if any(c == GARBAGE for c in row))
    check("4 garbage rows applied on spawn", rows_with_garbage == 4)
    check("incoming cleared after apply", llm.incoming_count() == 0)


def test_full_loop():
    import pygame
    from tetris.main import BattleTetris, load_config
    cfg = load_config()
    cfg["game"]["seed"] = 42
    game = BattleTetris(cfg, no_llm=True, start_paused=False)
    try:
        game.run(max_frames=400)
        check("full loop ran 400 frames without crashing", True)
        progressed = game.player.pieces_placed + game.llm.pieces_placed
        check("pieces were placed during the loop", progressed > 0)
    finally:
        try:
            pygame.quit()
        except Exception:
            pass


def test_ai_vs_ai():
    import pygame
    from tetris.main import BattleTetris, load_config
    cfg = load_config()
    cfg["game"]["seed"] = 11
    game = BattleTetris(cfg, no_llm=True, start_paused=False)
    game.vs_mode = "ai"
    game.reset()
    try:
        check("left controller created in ai mode", game.controller_left is not None)
        game.run(max_frames=300)
        check("AI vs AI ran 300 frames without crashing", True)
        check("both AI boards placed pieces",
              game.player.pieces_placed > 0 and game.llm.pieces_placed > 0)
    finally:
        try:
            pygame.quit()
        except Exception:
            pass


def test_garbage_default_off():
    from tetris.main import BattleTetris, load_config
    from tetris.game import Game
    from tetris.constants import COLS, ROWS
    from tetris.pieces import Piece
    cfg = load_config()
    check("garbage_enabled defaults off", cfg["game"].get("garbage_enabled", False) is False)
    g = BattleTetris(cfg, no_llm=True)
    check("effective garbage multiplier is 0 when off", g.garbage_mult == 0)
    g.client.shutdown(); g.client_left.shutdown()
    # a Game with multiplier 0: clearing a line sends 0 attack
    game = Game(random.Random(1), 800, 500, 0)
    for x in range(COLS):
        game.board.grid[ROWS - 1][x] = "L"
    game.current = Piece("I", rot=1, px=0)
    res = game.hard_drop()
    check("clearing a row sends no garbage when off", res.lines >= 1 and res.attack == 0)


def test_continuous_restart():
    import pygame
    from tetris.main import BattleTetris, load_config
    cfg = load_config()
    cfg["game"]["seed"] = 9
    # NEW default: continuous starts PAUSED (press P), it no longer auto-starts
    g0 = BattleTetris(cfg, no_llm=True, ai=True, continuous=True)
    check("continuous starts paused (press P to begin)", g0.state == "paused")
    g0.client.shutdown(); g0.client_left.shutdown()
    # once playing, a game-over auto-restarts without pausing
    game = BattleTetris(cfg, no_llm=True, ai=True, continuous=True, start_paused=False)
    try:
        check("plays when start_paused is False", game.state == "playing")
        game.player.dead = True
        game.step(16)
        check("game over recorded", game.state == "over")
        won = game.score_right
        check("win tallied", won >= 1)
        for _ in range(180):       # > CONTINUOUS_RESTART_MS of game time
            game.step(20)
        check("auto-restarted to playing (no pause)", game.state == "playing")
        check("scoreboard persisted across auto-restart", game.score_right >= won)
    finally:
        game.client.shutdown(); game.client_left.shutdown()
        try:
            pygame.quit()
        except Exception:
            pass


if __name__ == "__main__":
    print("== shapes =="); test_shapes()
    print("== bag =="); test_bag()
    print("== drop & clear =="); test_drop_and_clear()
    print("== garbage =="); test_garbage()
    print("== kicks =="); test_kicks()
    print("== enumerate =="); test_enumerate()
    print("== parser =="); test_parser()
    print("== attack exchange =="); test_attack_exchange()
    print("== full loop (dummy video, no network) =="); test_full_loop()
    print("== ai vs ai loop =="); test_ai_vs_ai()
    print("== garbage off by default =="); test_garbage_default_off()
    print("== continuous auto-restart =="); test_continuous_restart()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
