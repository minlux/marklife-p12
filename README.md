# p12print – Marklife P12 per USB ansteuern

Kleines Python-CLI-Tool, das Text auf einem **Marklife P12** Thermo-Labeldrucker
ausdruckt – über USB statt Bluetooth. Der Drucker meldet sich unter Linux als
USB-Printer-Class-Gerät (`09c7:0011`) an, der Kernel-Treiber `usblp` stellt ihn
als `/dev/usb/lpN` bereit. Das Tool schreibt den Druckjob direkt in dieses
Device-File; CUPS oder zusätzliche Treiber sind nicht nötig.

## Voraussetzungen

- Python 3
- [Pillow](https://pypi.org/project/pillow/) (`pip install pillow` bzw. `apt install python3-pil`)
- optional `fc-match` (fontconfig) zum Auflösen von Schriftnamen
- Schreibrechte auf das Device-File. `/dev/usb/lpN` gehört standardmäßig der
  Gruppe `lp`, daher den Benutzer ggf. hinzufügen:

  ```bash
  sudo usermod -aG lp $USER   # danach neu anmelden
  ```

Welches Device-File zum Drucker gehört, zeigt z. B.:

```bash
lsusb | grep 09c7:0011
ls -l /dev/usb/
```

## Verwendung

```bash
./p12print.py --usb /dev/usb/lp3 "Hallo Welt"
```

Die Schrift wird automatisch so groß gewählt, dass sie die volle Bandbreite
(12 mm) ausnutzt. Das Label ist so lang wie der Text (plus 1 mm Rand an jeder
Seite). Nach dem Druck wird das Band um 10 mm vorgeschoben, damit das Label
vollständig hinter dem Abreißmesser herausschaut.

### Beispiele

```bash
# mehrzeilig (ein wörtliches \n trennt Zeilen)
./p12print.py --usb /dev/usb/lp3 "Zeile 1\nZeile 2"

# mehrzeilig, zentriert (Default: linksbündig)
./p12print.py --usb /dev/usb/lp3 --align center "Kurz\nEine lange Zeile"

# feste Labellänge 40 mm, Text wird eingepasst
./p12print.py --usb /dev/usb/lp3 --length 40 "Kabel HDMI"

# feste Schriftgröße (in Dots, 8 Dots = 1 mm)
./p12print.py --usb /dev/usb/lp3 --size 48 "Kleiner"

# andere Schrift
./p12print.py --usb /dev/usb/lp3 --font "DejaVu Serif" "Serif"

# nur Vorschau als PNG, nichts drucken
./p12print.py --usb /dev/usb/lp3 --dry-run --preview label.png "Test"

# gestanzte Etiketten mit Lücken: bis zur nächsten Lücke vorschieben
./p12print.py --usb /dev/usb/lp3 --gap --length 40 "Etikett"
```

### Wie viele Zeilen?

Es gibt kein festes Limit – die Schrift wird so verkleinert, dass alle Zeilen
in die 12 mm Bandbreite passen. Bei Default-Rand (1 mm) ergibt sich ungefähr:

| Zeilen | Schrifthöhe |
| --- | --- |
| 1 | ~10 mm |
| 2 | ~5 mm |
| 3 | ~3,1 mm |
| 4 | ~2,3 mm |
| 5 | ~1,9 mm |
| 6 | ~1,4 mm |

Gut lesbar sind etwa **3–4 Zeilen**, 5 geht noch. Mit `--margin 2` wird
jede Zeile etwas größer.

### Optionen

| Option | Beschreibung | Default |
| --- | --- | --- |
| `--usb DEVICE` | usblp-Device-File, z. B. `/dev/usb/lp3` (Pflicht) | – |
| `text …` | zu druckender Text; mehrere Argumente werden mit Leerzeichen verbunden, `\n` = neue Zeile | – |
| `--length MM` | Labellänge entlang des Bandes, `0` = so lang wie der Text | `0` |
| `--width MM` | bedruckbare Breite quer zum Band (max. 12) | `12` |
| `--font FONT` | Font-Datei oder fontconfig-Name | `DejaVu Sans:bold` |
| `--size DOTS` | Schriftgröße in Dots | automatisch |
| `--align A` | Ausrichtung der Zeilen: `left`, `center`, `right` | `left` |
| `--margin DOTS` | Rand in Dots | `8` (1 mm) |
| `--feed MM` | Vorschub nach dem Druck (max. ~31) | `10` |
| `--gap` | bis zur nächsten Etikettenlücke vorschieben (nur bei gestanzten Etiketten!) | aus |
| `--density N` | Druckdichte: 1 hell, 2 normal, 3 dunkel | Druckereinstellung |
| `--flip` | Text um 180° drehen | aus |
| `--copies N` | Anzahl Kopien | `1` |
| `--preview PNG` | gerendertes Label zusätzlich als PNG speichern | – |
| `--dry-run` | nichts an den Drucker senden | aus |

> **Achtung:** `--gap` auf Endlosband führt dazu, dass der Drucker nach einer
> Lücke sucht, die es nicht gibt, und ca. 13 cm leeres Band ausgibt.

## Protokoll

Der P12 spricht das sog. **L11**-Protokoll – über USB dieselben Bytes wie über
Bluetooth. Der Druckkopf ist 96 Dots (12 Byte) breit bei 203 dpi (8 Dots/mm).
Da das Band längs durchläuft, wird der Text quer gerendert und um 90° gedreht.

```
[density]  1F 70 02 dd                      optional, dd = 1..3
[wakeup]   00 × 15
[enable]   10 FF F1 02
[raster]   1D 76 30 00 wL wH hL hH + Daten  GS v 0: Breite in Bytes, Höhe in Dots,
                                            Zeilen MSB-first, 1 = schwarz
[advance]  1B 4A nn                         Endlosband: nn Dots vorschieben
           1D 0C                            gestanzte Etiketten: zur Lücke
[stop]     10 FF F1 45
```

Laut Dokumentation bestätigt der Drucker einen Job mit `0xAA`. Über `usblp`
kommt diese Antwort in der Praxis meist nicht an; das Tool meldet dann
„no ack received“, der Druck funktioniert trotzdem.

## Quellen

`p12print.py` ist eine eigenständige Python-Implementierung; es wird kein Code
aus anderen Projekten verwendet. Das Wissen über das Druckerprotokoll stammt
aus folgenden Projekten (beide in TypeScript, primär für Bluetooth):

- [thermal-label/marklife](https://github.com/thermal-label/marklife) –
  Beschreibung des L11-Protokolls (`docs/protocol/l11.md`): Befehlsfolge,
  Rasterformat, 96 Dots Kopfbreite. Bestätigt außerdem, dass der P12 per USB
  druckt, inkl. USB-ID `09c7:0011` (`HARDWARE.md`).
- [tomLadder/thermoprint](https://github.com/tomLadder/thermoprint) –
  Reverse Engineering der Marklife-Drucker (`REVERSE_ENGINEERING.md`); die
  Befehlsbytes wurden mit dessen Implementierung
  (`packages/core/src/protocol/l11/commands.ts`) abgeglichen.

Textrendering, Rotation, automatische Schriftgröße, Ausrichtung sowie
Längen- und Vorschub-Logik (10 mm bis hinter das Abreißmesser) sind eigene
Umsetzung bzw. am echten Gerät ermittelt.
