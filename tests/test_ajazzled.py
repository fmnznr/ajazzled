import pytest

from ajazzled import Keyboard, keymap
from ajazzled import protocol as P
from ajazzled.__main__ import main, text_frames
from ajazzled.transport import SimTransport


def test_global_packet_matches_openajazz():
    pkt = P.build_packet(P.CMD_WRITE_CONFIG, 0, P.global_effect_payload(1, 2, 3, mode=5, brightness=4, speed=2),
                         fixed_checksum=P.OPENAJAZZ_FIXED_CHECKSUM)
    assert len(pkt) == 64
    assert pkt[:5] == bytes([0x04, 0x2A, 0x3D, 0x06, 0x1D])
    assert pkt[9:17] == bytes([5, 4, 2, 0, 0, 1, 2, 3])
    assert not any(pkt[17:])


def test_checksum():
    pkt = P.build_packet(P.CMD_SEND_DYNAMIC_COLORS, 0x0102, b"\xff\x01")
    assert pkt[1] | pkt[2] << 8 == 0x12 + 2 + 2 + 1 + 0xFF + 1


def test_whitelist():
    for cmd in (0x00, 0x04, 0x07, 0x0C, 0x20, 0xFF):
        with pytest.raises(P.ProtocolError):
            P.build_packet(cmd)
    with pytest.raises(P.ProtocolError):
        P.build_packet(P.CMD_WRITE_CONFIG, 0xC0, b"\0\0")


def test_keymap_unique():
    idx = keymap.guessed_indices()
    assert len(set(idx.values())) == len(idx) == len(keymap.KEY_NAMES)
    assert len(keymap.KEY_AT) == len(keymap.GRID)


def test_frames_and_diff():
    sim = SimTransport()
    kb = Keyboard(sim, keepalive=False)
    assert kb.map_size == 126
    assert kb.set_frame({"a": (1, 2, 3), "esc": (9, 9, 9)}) == 7  # first frame: everything
    i = kb.indices["a"] * 3
    assert bytes(sim.colors[i:i + 3]) == b"\x01\x02\x03"
    assert bytes(sim.colors[0:3]) == b"\x09\x09\x09"
    assert kb.set_frame({"a": (1, 2, 3), "esc": (9, 9, 9)}) == 0  # unchanged
    n = len(sim.log)
    kb.set_key("esc", 0, 0, 0)
    assert len(sim.log) == n + 1 and sim.colors[0] == 0
    kb.close()
    assert sim.log[-1][3] == P.CMD_END_DYNAMIC_COLORS and not sim.direct


def test_error_status():
    sim = SimTransport()
    kb = Keyboard(sim, keepalive=False)
    sim.read = lambda timeout_ms=None: bytes([4, 0, 0, P.CMD_READ_CAPABILITIES, 0, 0, 0, 1]) + bytes(56)
    with pytest.raises(P.ProtocolError):
        kb.read_capabilities()


def test_report_sizes():
    desc = bytes.fromhex("06 1c ff 09 92 a1 01 85 04 15 00 26 ff 00 75 08 95 3f 09 00 91 02 95 3f 09 00 81 02 c0")
    assert P.report_sizes(desc) == {("output", 4): 63, ("input", 4): 63}


def test_text_and_cli():
    frames = list(text_frames("HI", (1, 1, 1)))
    assert frames[0] == {} and any(frames)
    main(["--simulate", "bench", "--frames", "5"])
    with pytest.raises(SystemExit):
        main(["key", "a", "1", "2", "3"])
