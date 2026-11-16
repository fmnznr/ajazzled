"""AK820 ISO-DE keymap: name -> (led index, row, column).

row/column form a 6 x 15 pixel grid (stagger ignored) used for patterns and
scrolling text. The LED index is the position of the key in the keyboard's
colour buffer.

!! The LED indices below are a GUESS (EVision boards usually use
!! index = column * 6 + row). Run `python -m ajazzled calibrate` once; it
!! writes the verified table to keymap_iso_de.json, which then takes priority.
"""

from __future__ import annotations

import json
from pathlib import Path

ROWS, COLS = 6, 15
OVERRIDE_FILE = Path(__file__).with_name("keymap_iso_de.json")

# (row, [(name, column), ...])
_LAYOUT = [
    (0, [("esc", 0), ("f1", 1), ("f2", 2), ("f3", 3), ("f4", 4), ("f5", 5), ("f6", 6),
         ("f7", 7), ("f8", 8), ("f9", 9), ("f10", 10), ("f11", 11), ("f12", 12), ("del", 13)]),
    (1, [("^", 0), ("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 5), ("6", 6), ("7", 7),
         ("8", 8), ("9", 9), ("0", 10), ("ß", 11), ("´", 12), ("backspace", 13), ("home", 14)]),
    (2, [("tab", 0), ("q", 1), ("w", 2), ("e", 3), ("r", 4), ("t", 5), ("z", 6), ("u", 7),
         ("i", 8), ("o", 9), ("p", 10), ("ü", 11), ("+", 12), ("enter", 13), ("pgup", 14)]),
    (3, [("caps", 0), ("a", 1), ("s", 2), ("d", 3), ("f", 4), ("g", 5), ("h", 6), ("j", 7),
         ("k", 8), ("l", 9), ("ö", 10), ("ä", 11), ("#", 12), ("pgdn", 14)]),
    (4, [("lshift", 0), ("<", 1), ("y", 2), ("x", 3), ("c", 4), ("v", 5), ("b", 6), ("n", 7),
         ("m", 8), (",", 9), (".", 10), ("-", 11), ("rshift", 12), ("up", 13), ("end", 14)]),
    (5, [("lctrl", 0), ("win", 1), ("lalt", 2), ("space", 6), ("altgr", 9), ("fn", 10),
         ("rctrl", 11), ("left", 12), ("down", 13), ("right", 14)]),
]

GRID: dict[str, tuple[int, int]] = {name: (row, col) for row, keys in _LAYOUT for name, col in keys}
KEY_AT: dict[tuple[int, int], str] = {pos: name for name, pos in GRID.items()}
KEY_NAMES = list(GRID)


def guessed_indices() -> dict[str, int]:
    return {name: col * 6 + row for name, (row, col) in GRID.items()}


def load_indices() -> tuple[dict[str, int], bool]:
    """Returns (name -> led index, verified?)."""
    if OVERRIDE_FILE.exists():
        data = json.loads(OVERRIDE_FILE.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in data.items() if v is not None}, True
    return guessed_indices(), False


def save_indices(indices: dict[str, int]) -> None:
    OVERRIDE_FILE.write_text(json.dumps(indices, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
