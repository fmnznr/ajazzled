#!/usr/bin/env python3
"""Decode a capture from webhid_logger.js:  python tools/analyze_capture.py ak820-capture.json

Prints every packet in EVision-V2 terms, flags commands outside the lighting
whitelist (never replay those), and per MARK section lists which LED indices
were written with which colour -> that is the key -> index table.
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ajazzled import protocol as P  # noqa: E402

COLOR_CMDS = (P.CMD_WRITE_CUSTOM_COLORS, P.CMD_SEND_DYNAMIC_COLORS)


def main(path: str) -> None:
    log = json.loads(Path(path).read_text(encoding="utf-8"))
    counts: Counter = Counter()
    bad_sum = 0
    buf: dict[int, int] = {}
    section = "(Start)"
    changes: list[tuple[str, int, tuple]] = []

    def led_changes(off: int, data: bytes) -> None:
        touched = set()
        for i, v in enumerate(data):
            if buf.get(off + i, 0) != v:
                touched.add((off + i) // 3)
            buf[off + i] = v
        for led in sorted(touched):
            changes.append((section, led, tuple(buf.get(led * 3 + k, 0) for k in range(3))))

    for e in log:
        if e["dir"] == "MARK":
            section = e["label"]
            print(f"\n===== MARK {section} =====")
            continue
        if e["dir"] == "DEVICE":
            print("DEVICE", e.get("dev"), e.get("product"), json.dumps(e.get("collections")))
            continue
        pkt = bytes([e["rid"]]) + bytes.fromhex(e["data"])
        if e["rid"] != P.REPORT_ID or len(pkt) < 8:
            counts[(e["dir"], f"report id {e['rid']}")] += 1
            print(f"{e['t']:8d} {e['dir']:11s} id={e['rid']} ANDERE REPORT-ID: {e['data']}")
            continue
        cmd, size, off = pkt[3], pkt[4], pkt[5] | pkt[6] << 8
        name = P.ALLOWED_COMMANDS.get(cmd, "!! UNBEKANNT - NICHT NACHSENDEN !!")
        ok = P.checksum(pkt[:P.PACKET_LEN]) == pkt[1] | pkt[2] << 8
        bad_sum += not ok
        counts[(e["dir"], f"0x{cmd:02X} {name}")] += 1
        data = pkt[8:8 + size]
        print(f"{e['t']:8d} {e['dir']:11s} cmd=0x{cmd:02X} {name:22s} size={size:2d} off=0x{off:04X} "
              f"st={pkt[7]} sum={'ok' if ok else pkt[1:3].hex()} len={len(pkt)} | {data.hex(' ')}")
        if e["dir"] == "OUT" and cmd in COLOR_CMDS:
            led_changes(off, data)

    print("\n--- Zusammenfassung ---")
    for (d, name), n in sorted(counts.items()):
        print(f"{n:5d}  {d:11s} {name}")
    print(f"Pakete mit abweichender Prüfsumme: {bad_sum}")
    if changes:
        print("\n--- Geänderte LEDs je Markierung (Index = Byte-Offset / 3) ---")
        for sec, led, rgb in changes:
            if any(rgb):
                print(f"{sec:20s} LED {led:3d}  rgb={rgb}")


if __name__ == "__main__":
    main(sys.argv[1])
