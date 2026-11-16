"""High-level API: per-key colours via the volatile direct mode (nothing is
written to flash, so it is safe to animate)."""

from __future__ import annotations

import threading
import time

from . import keymap
from . import protocol as P

Color = tuple[int, int, int]


class Keyboard:
    def __init__(self, transport=None, map_size: int | None = None, keepalive: bool = True):
        if transport is None:
            from .transport import HidTransport
            transport = HidTransport()
        self.t = transport
        self._lock = threading.RLock()
        self.indices, self.keymap_verified = keymap.load_indices()
        self._map_size = map_size
        self._frame = bytearray()
        self._sent: bytearray | None = None
        self._last_tx = 0.0
        self._keepalive_on = keepalive
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ---- raw protocol -------------------------------------------------
    def query(self, cmd: int, offset: int = 0, payload: bytes = b"", size: int | None = None,
              fixed_checksum=None, need_reply: bool = True) -> bytes:
        pkt = P.build_packet(cmd, offset, payload, size, fixed_checksum)
        with self._lock:
            self.t.write(pkt)
            self._last_tx = time.monotonic()
            reply = self.t.read()
        if not reply:
            if need_reply:
                raise P.ProtocolError(f"no reply to cmd 0x{cmd:02X}")
            return b""
        return P.parse_reply(reply, cmd, offset)

    def read_capabilities(self) -> dict:
        d = self.query(P.CMD_READ_CAPABILITIES, size=7)
        if len(d) < 7 or d[0] != 0xAA or d[1] != 0x55:
            raise P.ProtocolError(f"unexpected capabilities: {d.hex(' ')}")
        return {"raw": d.hex(" "), "map_size": d[5], "macro_bytes": d[6] * 0x80}

    @property
    def map_size(self) -> int:
        if self._map_size is None:
            self._map_size = self.read_capabilities()["map_size"]
        return self._map_size

    # ---- global effects (the report openajazz sends) -------------------
    def global_effect(self, r: int, g: int, b: int, mode: int = 6, brightness: int = 4,
                      speed: int = 2, direction: int = 0, rainbow: bool = False,
                      openajazz_bytes: bool = True) -> bytes:
        """Set a built-in effect. Persistent (stored by the keyboard), so do
        not call this in an animation loop."""
        payload = P.global_effect_payload(r, g, b, mode, brightness, speed, direction, rainbow)
        fixed = P.OPENAJAZZ_FIXED_CHECKSUM if openajazz_bytes else None
        return self.query(P.CMD_WRITE_CONFIG, 0, payload, fixed_checksum=fixed, need_reply=False)

    # ---- per-key direct mode ------------------------------------------
    def _ensure_frame(self) -> None:
        if not self._frame:
            self._frame = bytearray(3 * self.map_size)

    def _led(self, key: str | int) -> int:
        idx = key if isinstance(key, int) else self.indices[key.lower()]
        if not 0 <= idx < self.map_size:
            raise KeyError(f"LED index {idx} outside 0..{self.map_size - 1}")
        return idx

    def put(self, key: str | int, r: int, g: int, b: int) -> None:
        """Change one key in the frame buffer without sending."""
        self._ensure_frame()
        i = self._led(key) * 3
        self._frame[i:i + 3] = bytes((r & 255, g & 255, b & 255))

    def fill(self, r: int, g: int, b: int) -> None:
        self._ensure_frame()
        self._frame[:] = bytes((r & 255, g & 255, b & 255)) * self.map_size

    def set_key(self, key: str | int, r: int, g: int, b: int) -> None:
        """Colour one key (name from the ISO-DE keymap or raw LED index) now."""
        self.put(key, r, g, b)
        self.show()

    def set_frame(self, colors: dict[str | int, Color], background: Color = (0, 0, 0)) -> int:
        """Replace the whole picture: {key: (r, g, b)}; other keys get `background`.
        Returns the number of packets sent."""
        self.fill(*background)
        for key, (r, g, b) in colors.items():
            self.put(key, r, g, b)
        return self.show()

    def set_pixels(self, pixels: dict[tuple[int, int], Color], background: Color = (0, 0, 0)) -> int:
        """Like set_frame but addressed as (row, col) on the 6 x 15 grid;
        positions without a key are ignored."""
        return self.set_frame({keymap.KEY_AT[p]: c for p, c in pixels.items() if p in keymap.KEY_AT},
                              background)

    def show(self, force: bool = False) -> int:
        """Send the frame buffer; only 56-byte chunks that changed are transmitted."""
        self._ensure_frame()
        sent = 0
        with self._lock:
            for off in range(0, len(self._frame), P.MAX_PAYLOAD):
                chunk = bytes(self._frame[off:off + P.MAX_PAYLOAD])
                if force or self._sent is None or self._sent[off:off + P.MAX_PAYLOAD] != chunk:
                    self.query(P.CMD_SEND_DYNAMIC_COLORS, off, chunk)
                    sent += 1
            self._sent = bytearray(self._frame)
        self._start_keepalive()
        return sent

    def _start_keepalive(self) -> None:
        # Without traffic the firmware drops back to its stored effect, so
        # re-send one unchanged byte when idle (OpenRGB does the same at 200 ms).
        if self._keepalive_on and self._thread is None:
            self._thread = threading.Thread(target=self._keepalive_loop, daemon=True)
            self._thread.start()

    def _keepalive_loop(self) -> None:
        while not self._stop.wait(0.05):
            with self._lock:
                if self._sent is not None and time.monotonic() - self._last_tx > 0.15:
                    try:
                        self.query(P.CMD_SEND_DYNAMIC_COLORS, 0, bytes(self._sent[:1]))
                    except Exception:
                        return

    def end_direct(self) -> None:
        """Leave direct mode; the keyboard returns to its stored effect."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
        self._stop.clear()
        if self._sent is not None:
            self._sent = None
            self.query(P.CMD_END_DYNAMIC_COLORS, need_reply=False)

    def close(self) -> None:
        try:
            self.end_direct()
        finally:
            self.t.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
