"""HID transport (hidapi) plus a simulator that speaks the same protocol."""

from __future__ import annotations

from . import protocol as P

VID = 0x320F
PID = 0x505B
USAGE_PAGE = 0xFF1C


def enumerate_interfaces(vid: int = VID, pid: int = PID) -> list[dict]:
    import hid
    return hid.enumerate(vid, pid)


class HidTransport:
    """Vendor interface of the AK820 (usage page 0xFF1C)."""

    def __init__(self, vid: int = VID, pid: int = PID, usage_page: int = USAGE_PAGE,
                 timeout_ms: int = 500):
        import hid
        infos = [d for d in hid.enumerate(vid, pid) if d.get("usage_page") == usage_page]
        if not infos:
            raise P.ProtocolError(
                f"no HID interface {vid:04X}:{pid:04X} with usage page 0x{usage_page:04X} found "
                "(run `python -m ajazzled probe`)")
        self.info = infos[0]
        self.dev = hid.device()
        self.dev.open_path(self.info["path"])
        self.timeout_ms = timeout_ms
        # openajazz writes 65 bytes, OpenRGB 64. Start with 64 (what the packet
        # layout implies) and fall back once if the OS rejects the length.
        self._pad = 0

    def report_descriptor(self) -> bytes | None:
        try:
            return bytes(self.dev.get_report_descriptor())
        except Exception:
            return None

    def write(self, packet: bytes) -> None:
        n = self.dev.write(packet + bytes(self._pad))
        if n < 0 and self._pad == 0:
            self._pad = 1
            n = self.dev.write(packet + b"\x00")
        if n < 0:
            raise P.ProtocolError(f"hid write failed: {self.dev.error()}")

    def read(self, timeout_ms: int | None = None) -> bytes:
        """Next report with ID 4, or b'' on timeout."""
        t = self.timeout_ms if timeout_ms is None else timeout_ms
        while True:
            data = bytes(self.dev.read(P.PACKET_LEN + 1, t))
            if not data or data[0] == P.REPORT_ID:
                return data

    def drain(self) -> None:
        while self.dev.read(P.PACKET_LEN + 1, 1):
            pass

    def close(self) -> None:
        self.dev.close()


class SimTransport:
    """Offline stand-in: answers like an EVision-V2 keyboard and keeps the
    direct-mode colour buffer so frames can be previewed in the terminal."""

    def __init__(self, map_size: int = 126):
        self.map_size = map_size
        self.colors = bytearray(3 * map_size)
        self.direct = False
        self.log: list[bytes] = []
        self._reply = b""

    def report_descriptor(self):
        return None

    def write(self, packet: bytes) -> None:
        self.log.append(packet)
        cmd, size, off = packet[3], packet[4], packet[5] | packet[6] << 8
        reply = bytearray(packet[:P.PACKET_LEN])
        if cmd == P.CMD_READ_CAPABILITIES:
            reply[8:15] = bytes([0xAA, 0x55, 0, 0, 0, self.map_size, 0])
        elif cmd == P.CMD_SEND_DYNAMIC_COLORS:
            self.colors[off:off + size] = packet[8:8 + size][:max(0, len(self.colors) - off)]
            self.direct = True
        elif cmd == P.CMD_END_DYNAMIC_COLORS:
            self.direct = False
        self._reply = bytes(reply)

    def read(self, timeout_ms=None) -> bytes:
        r, self._reply = self._reply, b""
        return r

    def drain(self) -> None:
        self._reply = b""

    def close(self) -> None:
        pass
