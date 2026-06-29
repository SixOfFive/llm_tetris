"""Render the game headlessly and save PNG screenshots, and exercise the real
LLM endpoint. Run:  python tests/capture.py [--llm] [--frames N]"""

import argparse
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import random
import pygame
from tetris.main import BattleTetris, load_config
from tetris.board import Board
from tetris.pieces import Piece
from tetris.llm_player import LLMClient


def test_real_llm():
    cfg = load_config()
    client = LLMClient(cfg["llm"])
    b = Board()
    # build a simple stack so the menu is interesting
    for x in range(10):
        if x not in (4, 5):
            b.grid[19][x] = "L"
    piece = Piece("I")
    print(f"[llm] endpoint={client.base_url} model={client.model}")
    client.request_move(b, piece, "T", 0)
    t0 = time.monotonic()
    res = None
    while res is None and time.monotonic() - t0 < client.timeout + 5:
        res = client.poll()
        time.sleep(0.05)
    client.shutdown()
    if res is None:
        print("[llm] TIMEOUT - no result"); return False
    print(f"[llm] source={res.source} latency={res.latency:.2f}s "
          f"placement={(res.placement.rot, res.placement.px, res.placement.lines) if res.placement else None}")
    print(f"[llm] reason={res.reason!r}")
    print(f"[llm] raw={res.raw[:200]!r}")
    return res.source == "llm"


def capture(use_llm, frames, out, ai=False):
    cfg = load_config()
    cfg["game"]["seed"] = 3
    game = BattleTetris(cfg, no_llm=not use_llm, start_paused=False)
    if ai:
        game.vs_mode = "ai"
        game.reset()
    clock = pygame.time.Clock()
    think_frames = place_frames = 0
    for _ in range(frames):
        dt = clock.tick(60)
        game.step(dt)
        game.render()
        st = game.controller.status
        if st.startswith("Thinking"):
            think_frames += 1
        elif st.startswith("Placing"):
            place_frames += 1
    pygame.image.save(game.screen, out)
    print(f"[capture] saved {out}  "
          f"(left pieces={game.player.pieces_placed}, right pieces={game.llm.pieces_placed}, "
          f"mode={game.vs_mode}, state={game.state})")
    if use_llm and not ai:
        tot = think_frames + place_frames or 1
        print(f"[pipeline] thinking frames={think_frames} ({100*think_frames//tot}%)  "
              f"placing/animating frames={place_frames} ({100*place_frames//tot}%)")
        print("[pipeline] recent LLM replies:")
        for line in game.controller.log[-8:]:
            print("   " + line)
    game.client.shutdown()
    game.client_left.shutdown()
    pygame.quit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--ai", action="store_true", help="LLM vs LLM mode")
    ap.add_argument("--frames", type=int, default=220)
    args = ap.parse_args()

    if args.ai:
        capture(args.llm, args.frames, os.path.join(ROOT, "preview_ai.png"), ai=True)
    elif args.llm:
        ok = test_real_llm()
        print(f"[llm] functional test {'PASS' if ok else 'FAIL'}")
        capture(True, args.frames, os.path.join(ROOT, "preview_llm.png"))
    else:
        capture(False, args.frames, os.path.join(ROOT, "preview_nollm.png"))
