# ajazzled

Per-Key-RGB für die **Ajazz AK820** (ISO-DE, ohne Display, USB, `320F:505B`) mit Python auf macOS.

**Status:** Protokollschicht, Lib, Demos und Tools sind fertig und im Simulator getestet.
An echter Hardware ist bisher *nichts* gelaufen – siehe „Was gesichert ist“.

## Setup

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Was gesichert ist – und was Hypothese

| | Quelle | Status |
|---|---|---|
| Report-ID `0x04`, Cmd `0x06` (globaler Effekt) | openajazz, für AK820 implementiert | bestätigt (dort) |
| Paketformat = **EVision V2** (`04, sum_lo, sum_hi, cmd, size, off_lo, off_hi, status, 56 Byte Daten`) | openajazz-Report passt Byte für Byte auf OpenRGBs `EVisionV2KeyboardController` | sehr wahrscheinlich |
| Cmd `0x03` Capabilities lesen, `0x12` Farben direkt setzen (flüchtig), `0x13` Direktmodus beenden | OpenRGB, andere EVision-V2-Boards | **am AK820 unbestätigt** |
| LED-Index je Taste (`Spalte*6 + Zeile`) | geraten | **`calibrate` nötig** |

Die unbestätigten Befehle sind in der CLI hinter `--unverified-ok` gesperrt.
Die Lib kann grundsätzlich nur die Befehle der Whitelist in `ajazzled/protocol.py` senden
(Lighting/Config); alles andere – insbesondere Firmware-Befehle – wird abgelehnt.

## Schritte

### 1. Gerät prüfen (nur lesen)

```sh
system_profiler SPUSBDataType | grep -B3 -A8 -i "0x320f"
python -m ajazzled probe
```

Erwartet: eine Zeile mit `usage_page=0xFF1C  <-- Lighting-Interface`, dazu die Report-Größen.

### 2. Globaler Farbwechsel (Proof of Concept)

```sh
python -m ajazzled global 255 0 0            # rot, statisch (mode 6)
python -m ajazzled global 0 0 255 --mode 5   # blau, Atmen
```

Sendet exakt den openajazz-Report und gibt eine eventuelle Antwort (`RX …`) aus.
Dieser Befehl wird von der Tastatur gespeichert – nicht in Schleifen verwenden.

### 3. Per-Key-Protokoll mitschneiden (WebHID)

1. Web-Treiber in **Chrome** öffnen, DevTools → Konsole, Inhalt von
   `tools/webhid_logger.js` einfügen. Erst danach die Tastatur verbinden.
2. Vor jeder Aktion eine Markierung setzen, dann klicken:
   ```js
   __hidmark("Q rot")        // im Custom-Light-Modus Q rot färben (ggf. Übernehmen)
   __hidmark("W gruen")      // W grün
   __hidmark("Esc blau")     // Esc blau
   __hidmark("Space weiss")  // Leertaste weiß
   __hidmark("Rechts gelb")  // Pfeil rechts gelb
   __hidmark("global rot")   // zum Vergleich: statischer Effekt, rot
   __hidsave()               // lädt ak820-capture.json
   ```
3. **Nicht** auf Firmware-Update / Reset klicken.
4. `python tools/analyze_capture.py ak820-capture.json` – dekodiert alles, markiert
   unbekannte Befehle und listet je Markierung die geänderten LED-Indizes.

Falls der Web-Treiber die Tastatur nicht erkennt: Schritt 3 überspringen und direkt
die Hypothese testen (`caps`, dann `key`).

### 4. Lib

```sh
python -m ajazzled --unverified-ok caps                 # liest map_size
python -m ajazzled --unverified-ok key 0 255 0 0 --index   # LED 0 rot, 5 s
python -m ajazzled --unverified-ok calibrate            # schreibt ajazzled/keymap_iso_de.json
```

```python
from ajazzled import Keyboard

with Keyboard() as kb:
    kb.set_key("q", 255, 0, 0)
    kb.set_frame({"w": (0, 255, 0), "enter": (0, 0, 255)}, background=(10, 10, 10))
    kb.set_pixels({(1, 3): (255, 255, 0)})   # (Zeile, Spalte) im 6x15-Raster
    input("Enter zum Beenden")
```

Die Farben gehen über den flüchtigen Direktmodus (kein Flash-Verschleiß); nur geänderte
56-Byte-Blöcke werden übertragen. Ein Keepalive-Thread hält den Modus, `close()` gibt
die Tastatur an ihren gespeicherten Effekt zurück.

### 5. Demos und Messung

```sh
python -m ajazzled --simulate text "HALLO"              # Vorschau im Terminal, ohne Tastatur
python -m ajazzled --unverified-ok text "HALLO" 0 255 255
python -m ajazzled --unverified-ok rainbow
python -m ajazzled --unverified-ok bench                # Frames/s
```

Erwartung für `bench`: ein Vollbild sind ca. 7 Pakete mit je einer Antwort; bei 1–2 ms pro
Paket also grob 50–150 Vollbilder/s, bei Diff-Übertragung mehr. Der echte Wert kommt aus `bench`.

## Tests

```sh
pip install pytest && python -m pytest -q
```
