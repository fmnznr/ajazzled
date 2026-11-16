"""EVision-V2 packet layer (the protocol family the AK820 320F:505B speaks).

Packet layout (report ID 0x04, 64 bytes incl. ID):
    [0]    report id (0x04)
    [1:3]  checksum, little endian = sum(bytes[3:]) & 0xFFFF
    [3]    command
    [4]    payload size
    [5:7]  offset, little endian
    [7]    status (0 in requests; non-zero in a reply = error)
    [8:]   payload (max 56 bytes)

Sources: openajazz (AK820 global effects) and OpenRGB's
EVisionV2KeyboardController (same packet layout, adds per-key commands).
"""

from __future__ import annotations

REPORT_ID = 0x04
PACKET_LEN = 64
MAX_PAYLOAD = PACKET_LEN - 8

CMD_BEGIN_CONFIGURE = 0x01
CMD_END_CONFIGURE = 0x02
CMD_READ_CAPABILITIES = 0x03
CMD_READ_CONFIG = 0x05
CMD_WRITE_CONFIG = 0x06
CMD_READ_CUSTOM_COLORS = 0x0A
CMD_WRITE_CUSTOM_COLORS = 0x0B
CMD_SEND_DYNAMIC_COLORS = 0x12
CMD_END_DYNAMIC_COLORS = 0x13

# Safety: this is the complete set of commands the library is able to send.
# Everything here is lighting/config related; anything else (in particular
# whatever the vendor tool uses for firmware updates) is refused.
ALLOWED_COMMANDS = {
    CMD_BEGIN_CONFIGURE: "begin_configure",
    CMD_END_CONFIGURE: "end_configure",
    CMD_READ_CAPABILITIES: "read_capabilities",
    CMD_READ_CONFIG: "read_config",
    CMD_WRITE_CONFIG: "write_config",
    CMD_READ_CUSTOM_COLORS: "read_custom_colors",
    CMD_WRITE_CUSTOM_COLORS: "write_custom_colors",
    CMD_SEND_DYNAMIC_COLORS: "send_dynamic_colors",
    CMD_END_DYNAMIC_COLORS: "end_dynamic_colors",
}

# WRITE_CONFIG may only touch: current-profile byte + 3 lighting profiles of 0x40.
CONFIG_WRITE_LIMIT = 0x01 + 3 * 0x40

# Checksum bytes openajazz sends verbatim for the AK820 (not a valid sum, so
# the firmware evidently does not verify it for WRITE_CONFIG).
OPENAJAZZ_FIXED_CHECKSUM = (0x2A, 0x3D)


class ProtocolError(Exception):
    pass


def checksum(packet: bytes) -> int:
    return sum(packet[3:]) & 0xFFFF


def build_packet(cmd: int, offset: int = 0, payload: bytes = b"", size: int | None = None,
                 fixed_checksum: tuple[int, int] | None = None) -> bytes:
    """Build one 64-byte packet. `size` overrides len(payload) for read requests."""
    if cmd not in ALLOWED_COMMANDS:
        raise ProtocolError(f"command 0x{cmd:02X} is not on the lighting whitelist")
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError("payload too long")
    size = len(payload) if size is None else size
    if not 0 <= size <= MAX_PAYLOAD or not 0 <= offset <= 0xFFFF:
        raise ProtocolError("size/offset out of range")
    if cmd == CMD_WRITE_CONFIG and offset + size > CONFIG_WRITE_LIMIT:
        raise ProtocolError("write_config outside the lighting profile area refused")
    buf = bytearray(PACKET_LEN)
    buf[0] = REPORT_ID
    buf[3] = cmd
    buf[4] = size
    buf[5] = offset & 0xFF
    buf[6] = offset >> 8
    buf[8:8 + len(payload)] = payload
    if fixed_checksum is None:
        c = checksum(buf)
        buf[1], buf[2] = c & 0xFF, c >> 8
    else:
        buf[1], buf[2] = fixed_checksum
    return bytes(buf)


def parse_reply(reply: bytes, cmd: int, offset: int) -> bytes:
    """Validate a reply to (cmd, offset) and return its payload."""
    if len(reply) < 8 or reply[0] != REPORT_ID:
        raise ProtocolError(f"unexpected reply: {bytes(reply).hex(' ')}")
    if reply[3] != cmd or reply[5] | reply[6] << 8 != offset:
        raise ProtocolError(f"reply does not echo request: {bytes(reply).hex(' ')}")
    if reply[7] != 0:
        raise ProtocolError(f"device returned status 0x{reply[7]:02X} for cmd 0x{cmd:02X}")
    return bytes(reply[8:8 + min(reply[4], MAX_PAYLOAD)])


def global_effect_payload(r: int, g: int, b: int, mode: int = 6, brightness: int = 4,
                          speed: int = 2, direction: int = 0, rainbow: bool = False) -> bytes:
    """The 29-byte WRITE_CONFIG payload at offset 0 exactly as openajazz sends it:
    [profile=0, mode, brightness, speed, direction, rainbow, r, g, b, 0...]."""
    p = bytearray(0x1D)
    p[1:9] = bytes([mode, brightness, speed, direction, 1 if rainbow else 0, r, g, b])
    return bytes(p)


def report_sizes(descriptor: bytes) -> dict[tuple[str, int], int]:
    """Parse a HID report descriptor -> {(kind, report_id): payload bytes}."""
    sizes: dict[tuple[str, int], int] = {}
    rsize = rcount = rid = 0
    stack: list[tuple[int, int, int]] = []
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == 0xFE:  # long item
            i += 3 + descriptor[i + 1]
            continue
        n = (0, 1, 2, 4)[prefix & 3]
        val = int.from_bytes(descriptor[i + 1:i + 1 + n], "little")
        tag = prefix & 0xFC
        if tag == 0x74:
            rsize = val
        elif tag == 0x94:
            rcount = val
        elif tag == 0x84:
            rid = val
        elif tag == 0xA4:
            stack.append((rsize, rcount, rid))
        elif tag == 0xB4 and stack:
            rsize, rcount, rid = stack.pop()
        elif tag in (0x80, 0x90, 0xB0):
            kind = {0x80: "input", 0x90: "output", 0xB0: "feature"}[tag]
            sizes[(kind, rid)] = sizes.get((kind, rid), 0) + rsize * rcount
        i += 1 + n
    return {k: (bits + 7) // 8 for k, bits in sizes.items()}
