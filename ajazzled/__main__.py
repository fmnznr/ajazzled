"""CLI: python -m ajazzled <command>   (see README)"""

from __future__ import annotations

import argparse
import colorsys
import sys
import time

from . import font, keymap
from . import protocol as P
from .keyboard import Keyboard
from .transport import PID, USAGE_PAGE, VID, SimTransport

UNVERIFIED = {"caps", "key", "calibrate", "text", "rainbow", "bench"}


def cmd_probe(args) -> None:
    """Read-only: list HID interfaces, never writes to the device."""
    from .transport import HidTransport, enumerate_interfaces
    infos = enumerate_interfaces()
    if not infos:
        import hid
        print(f"Kein Gerät {VID:04X}:{PID:04X} gefunden. Vorhandene Geräte mit Vendor-Usage-Page:")
        for d in hid.enumerate():
            if d.get("usage_page", 0) >= 0xFF00:
                print(f"  {d['vendor_id']:04X}:{d['product_id']:04X} usage_page=0x{d['usage_page']:04X} "
                      f"usage=0x{d['usage']:02X} {d.get('manufacturer_string')!r} {d.get('product_string')!r}")
        return
    for d in infos:
        mark = "  <-- Lighting-Interface" if d.get("usage_page") == USAGE_PAGE else ""
        print(f"{d['vendor_id']:04X}:{d['product_id']:04X} if={d.get('interface_number')} "
              f"usage_page=0x{d.get('usage_page', 0):04X} usage=0x{d.get('usage', 0):02X} "
              f"{d.get('manufacturer_string')!r} {d.get('product_string')!r}{mark}")
    try:
        t = HidTransport()
    except P.ProtocolError as e:
        print(f"\n{e}")
        return
    desc = t.report_descriptor()
    t.close()
    if desc is None:
        print("\nReport-Descriptor nicht lesbar (hidapi < 0.14?) – nicht schlimm.")
        return
    print(f"\nReport-Descriptor ({len(desc)} Bytes): {desc.hex(' ')}")
    for (kind, rid), n in sorted(P.report_sizes(desc).items()):
        print(f"  {kind:7s} report id {rid}: {n} Bytes Nutzdaten (+1 Byte ID)")


def cmd_global(kb: Keyboard, args) -> None:
    payload = P.global_effect_payload(args.r, args.g, args.b, args.mode, args.brightness, args.speed)
    pkt = P.build_packet(P.CMD_WRITE_CONFIG, 0, payload,
                         fixed_checksum=None if args.real_checksum else P.OPENAJAZZ_FIXED_CHECKSUM)
    print("TX", pkt.hex(" "))
    with kb._lock:
        kb.t.write(pkt)
        reply = kb.t.read(300)
    print("RX", reply.hex(" ") if reply else "(keine Antwort innerhalb 300 ms)")


def cmd_caps(kb: Keyboard, args) -> None:
    print(kb.read_capabilities())


def cmd_key(kb: Keyboard, args) -> None:
    key = int(args.key) if args.key.isdigit() and args.index else args.key
    kb.set_key(key, args.r, args.g, args.b)
    preview(kb)
    time.sleep(args.hold)


def cmd_calibrate(kb: Keyboard, args) -> None:
    guess = {v: k for k, v in keymap.guessed_indices().items()}
    result: dict[str, int] = {}
    print("Pro LED-Index leuchtet eine Taste weiß. Tastenname eingeben "
          "(Enter = Vorschlag übernehmen, '-' = nichts leuchtet, 'q' = speichern & Ende).")
    print("Gültige Namen:", " ".join(keymap.KEY_NAMES))
    for idx in range(kb.map_size):
        kb.set_frame({idx: (255, 255, 255)})
        while True:
            default = guess.get(idx, "-")
            ans = input(f"LED {idx:3d} [{default}]: ").strip().lower() or default
            if ans in ("-", "q") or ans in keymap.GRID:
                break
            print("  unbekannter Name")
        if ans == "q":
            break
        if ans != "-":
            result[ans] = idx
    keymap.save_indices(result)
    missing = [k for k in keymap.KEY_NAMES if k not in result]
    print(f"{len(result)} Tasten gespeichert in {keymap.OVERRIDE_FILE}")
    if missing:
        print("Ohne LED-Index:", " ".join(missing))


def text_frames(text: str, color):
    cols = [0] * keymap.COLS + font.text_columns(text) + [0] * keymap.COLS
    for start in range(len(cols) - keymap.COLS + 1):
        yield {(y, x): color for x in range(keymap.COLS) for y in range(font.HEIGHT)
               if cols[start + x] >> (font.HEIGHT - 1 - y) & 1}


def cmd_text(kb: Keyboard, args) -> None:
    for _ in range(args.loops):
        for px in text_frames(args.text, (args.r, args.g, args.b)):
            t0 = time.monotonic()
            kb.set_pixels(px)
            preview(kb)
            time.sleep(max(0, 1 / args.fps - (time.monotonic() - t0)))


def rainbow_frame(phase: float):
    return {(y, x): tuple(int(255 * c) for c in colorsys.hsv_to_rgb((x / keymap.COLS + y * 0.04 + phase) % 1, 1, 1))
            for y in range(keymap.ROWS) for x in range(keymap.COLS)}


def cmd_rainbow(kb: Keyboard, args) -> None:
    t_end = time.monotonic() + args.seconds
    while time.monotonic() < t_end:
        t0 = time.monotonic()
        kb.set_pixels(rainbow_frame(t0 * 0.3))
        preview(kb)
        time.sleep(max(0, 1 / args.fps - (time.monotonic() - t0)))


def cmd_bench(kb: Keyboard, args) -> None:
    def run(label, frames):
        pk, t0 = 0, time.perf_counter()
        for f in frames:
            pk += kb.set_pixels(f)
        dt = time.perf_counter() - t0
        n = len(frames)
        print(f"{label:28s} {n / dt:7.1f} fps   {pk / n:4.1f} Pakete/Frame   {1000 * dt / max(pk, 1):.2f} ms/Paket")

    n = args.frames
    run("Regenbogen (alles ändert sich)", [rainbow_frame(i / n) for i in range(n)])
    run("Lauftext (Diff-Übertragung)", list(text_frames("HALLO AK820 ", (255, 255, 255)))[:n])
    one = [{(1, 1 + i % 10): (255, 0, 0)} for i in range(n)]
    run("Einzelne Taste wandert", one)


def preview(kb: Keyboard) -> None:
    """Terminal picture of the frame when running with --simulate."""
    t = kb.t
    if not isinstance(t, SimTransport) or not sys.stdout.isatty():
        return
    out = ["\x1b[H"]
    for y in range(keymap.ROWS):
        for x in range(keymap.COLS):
            name = keymap.KEY_AT.get((y, x))
            if name is None or name not in kb.indices:
                out.append("   ")
                continue
            i = kb.indices[name] * 3
            r, g, b = t.colors[i:i + 3]
            out.append(f"\x1b[48;2;{r};{g};{b}m  \x1b[0m ")
        out.append("\n\n")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="ajazzled")
    ap.add_argument("--simulate", action="store_true", help="ohne Tastatur, Vorschau im Terminal")
    ap.add_argument("--unverified-ok", action="store_true",
                    help="Befehle erlauben, die am AK820 noch nicht bestätigt sind (0x03, 0x12, 0x13)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def rgb(p, default=None):
        for i, c in enumerate("rgb"):
            p.add_argument(c, type=int, **({} if default is None else {"nargs": "?", "default": default[i]}))

    sub.add_parser("probe", help="HID-Interfaces auflisten (nur lesen)")
    p = sub.add_parser("global", help="globaler Effekt/Farbe (openajazz-Report)")
    rgb(p)
    p.add_argument("--mode", type=int, default=6, help="1..18; 6 = statisch (OpenRGB), 5 = Atmen")
    p.add_argument("--brightness", type=int, default=4, choices=range(5))
    p.add_argument("--speed", type=int, default=2, choices=range(5))
    p.add_argument("--real-checksum", action="store_true", help="echte Prüfsumme statt 2A 3D")
    sub.add_parser("caps", help="Capabilities lesen (map_size)")
    p = sub.add_parser("key", help="eine Taste färben")
    p.add_argument("key")
    rgb(p)
    p.add_argument("--index", action="store_true", help="KEY ist ein LED-Index")
    p.add_argument("--hold", type=float, default=5)
    sub.add_parser("calibrate", help="LED-Index -> Taste zuordnen")
    p = sub.add_parser("text", help="Lauftext")
    p.add_argument("text")
    rgb(p, (255, 255, 255))
    p.add_argument("--fps", type=float, default=12)
    p.add_argument("--loops", type=int, default=3)
    p = sub.add_parser("rainbow")
    p.add_argument("--fps", type=float, default=30)
    p.add_argument("--seconds", type=float, default=10)
    p = sub.add_parser("bench", help="Frames/s messen")
    p.add_argument("--frames", type=int, default=200)
    args = ap.parse_args(argv)

    if args.cmd == "probe":
        return cmd_probe(args)
    if args.cmd in UNVERIFIED and not (args.simulate or args.unverified_ok):
        sys.exit(f"'{args.cmd}' nutzt Befehle, die am AK820 noch unbestätigt sind "
                 "(0x03/0x12/0x13, aus OpenRGB EVision-V2). Mit --unverified-ok freigeben.")
    kb = Keyboard(SimTransport() if args.simulate else None)
    if args.simulate and sys.stdout.isatty():
        sys.stdout.write("\x1b[2J")
    try:
        globals()[f"cmd_{args.cmd}"](kb, args)
    except KeyboardInterrupt:
        pass
    finally:
        kb.close()


if __name__ == "__main__":
    main()
