"""Static configuration: board dimensions, colours, timing and layout."""

# ---------------------------------------------------------------------------
# Board geometry
# ---------------------------------------------------------------------------
COLS = 10          # playfield width in cells
ROWS = 20          # visible playfield height in cells
CELL = 28          # pixel size of one cell

# ---------------------------------------------------------------------------
# Piece identifiers and guideline colours (RGB)
# ---------------------------------------------------------------------------
# Cell values stored in a board grid:
#   0           -> empty
#   "I".."L"    -> a locked tetromino cell (keyed by piece name)
#   "G"         -> garbage cell
PIECE_NAMES = ["I", "O", "T", "S", "Z", "J", "L"]

COLORS = {
    "I": (0, 240, 240),     # cyan
    "O": (240, 240, 0),     # yellow
    "T": (160, 0, 240),     # purple
    "S": (0, 240, 0),       # green
    "Z": (240, 0, 0),       # red
    "J": (0, 0, 240),       # blue
    "L": (240, 160, 0),     # orange
    "G": (110, 110, 120),   # garbage grey
}

# UI palette ----------------------------------------------------------------
BG_TOP = (14, 17, 23)
BG_BOTTOM = (7, 9, 14)
GRID_LINE = (32, 38, 50)
PANEL_BG = (18, 22, 30)
PANEL_BORDER = (44, 52, 68)
TEXT = (210, 217, 228)
TEXT_DIM = (130, 140, 156)
ACCENT = (88, 166, 255)
GHOST = (70, 78, 92)
WIN_COLOR = (90, 220, 130)
LOSE_COLOR = (235, 90, 90)
THINK_COLOR = (240, 200, 90)

# ---------------------------------------------------------------------------
# Layout (computed in pixels). Two boards side by side; LLM reply panel and
# player help panel sit underneath their respective boards.
# ---------------------------------------------------------------------------
MARGIN = 28
HUD_W = 150          # width of the next/score HUD beside each board
GUTTER = 34          # gap between a board and its HUD / the centre divider
BOARD_PX_W = COLS * CELL
BOARD_PX_H = ROWS * CELL
BOARD_TOP = 70
PANEL_H = 188        # height of the panels under each board

# x positions ---------------------------------------------------------------
PLAYER_BOARD_X = MARGIN + HUD_W + GUTTER
PLAYER_HUD_X = MARGIN
CENTER_X = PLAYER_BOARD_X + BOARD_PX_W + GUTTER          # centre divider
LLM_BOARD_X = CENTER_X + GUTTER
LLM_HUD_X = LLM_BOARD_X + BOARD_PX_W + GUTTER

WINDOW_W = LLM_HUD_X + HUD_W + MARGIN
WINDOW_H = BOARD_TOP + BOARD_PX_H + 16 + PANEL_H + MARGIN

# Panels (under each board) -------------------------------------------------
PANEL_Y = BOARD_TOP + BOARD_PX_H + 16
PLAYER_PANEL = (PLAYER_HUD_X, PANEL_Y, HUD_W + GUTTER + BOARD_PX_W, PANEL_H)
LLM_PANEL = (LLM_BOARD_X, PANEL_Y, BOARD_PX_W + GUTTER + HUD_W, PANEL_H)

# ---------------------------------------------------------------------------
# Default timing (overridable from config.json -> "game")
# ---------------------------------------------------------------------------
FPS = 60
DEFAULTS = {
    "player_gravity_ms": 800,
    "soft_drop_ms": 40,
    "lock_delay_ms": 500,
    "llm_anim_min_step_ms": 22,  # fastest per-step for the LLM piece animation
    "llm_anim_max_step_ms": 240,  # slowest per-step (keeps motion from looking frozen)
    "llm_speed_factor": 1.15,    # AI places this much faster than the human's pace
    "llm_max_cadence_ms": 6000,  # cap so the AI keeps moving even if the human idles
    "garbage_enabled": False,    # OFF by default: clearing lines does NOT attack the opponent
    "garbage_multiplier": 2,     # lines sent per line cleared, WHEN garbage_enabled is true
    "seed": None,
}

ASSET_DIR = "assets"
