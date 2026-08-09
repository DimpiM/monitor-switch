# Messprotokolle — Samsung Odyssey G9 (LC49G95T)

Alles hier Dokumentierte ist am realen Gerät gemessen, sofern nicht ausdrücklich als
„hergeleitet" oder „unverifiziert" markiert. Diese Datei ist die Beweisgrundlage des
Projekts — sie erklärt, warum `monitor-switch` so gebaut ist, wie es gebaut ist.

English version: [hardware-findings.md](hardware-findings.md)

| | |
|---|---|
| Monitor | Samsung Odyssey G9, **LC49G95T**, 5120×1440 |
| Scaler | Novatek, Capabilities-Kennung „FALCON", MCCS 2.0 |
| DP1 | Rechner A (Windows) |
| DP2 | Rechner B (Linux, KDE Plasma auf Wayland, Intel i915) |
| HDMI | Steuerkanal — Raspberry Pi Zero 2 W |

## Kernbefund

**DDC/CI funktioniert bei diesem Monitor nicht über DisplayPort — nur über HDMI.**

Der DDC/CI-Slave `0x37` antwortet auf den DisplayPort-Eingängen überhaupt nicht:

```
$ i2cdetect -y -r 14          # der Monitor über DisplayPort
30: 30 -- -- -- -- -- -- --   # nur EDID (0x50) und Segment-Pointer (0x30)
50: 50 -- -- -- -- -- -- --   # kein 0x37
```

```
$ ddcutil detect
Invalid display
   I2C bus:  /dev/i2c-14
   Model: LC49G95T
   This monitor does not support DDC/CI. (I2C slave address x37 is unresponsive.)
```

Am selben Rechner spricht ein danebenstehender Acer X34 P über DisplayPort sauber
DDC/CI (VCP 2.2). Es liegt also **nicht** an Treiber, GPU, Kabel oder Berechtigungen,
sondern an der Monitor-Firmware. Das deckt sich mit der Fehlerlage seit 2020, quer
über AMD- und Intel-GPUs, unabhängig von der im OSD gewählten DisplayPort-Version
und von Firmware-Updates (siehe Quellen).

Über HDMI dagegen antwortet der Monitor sauber — und zwar **auch dann, wenn HDMI gar
nicht der angezeigte Eingang ist.** HDMI kann also dauerhaft reiner Steuerkanal
bleiben, während das Bild über DisplayPort läuft. Das ist die Grundlage des ganzen
Aufbaus.

## Die Wertetabelle für VCP `0x60` (Input Source)

Die zentrale Falle: **Schreib- und Lesewerte sind verschieden.**

| Eingang | schreiben (`setvcp`) | lesen (`getvcp`) |
|---|---|---|
| **DP1** | **`0x0f`** | `0x03` |
| **DP2** | **`0x10`** | `0x04` |
| HDMI | `0x11` | `0x01` |

Geschrieben werden die **MCCS-Standardwerte**, zurückgemeldet werden herstellereigene.
`ddcutil` interpretiert den Lesewert `0x04` nach Norm und labelt ihn irreführend als
„DVI-2" — ein Anzeigeartefakt, kein Hinweis auf einen DVI-Eingang.

Messprotokoll des Durchlaufs, der die Schreibwerte ermittelt hat:

```
schreibe 0x01 : x04 -> x01  HDMI
schreibe 0x02 : x01 -> x01  (wirkungslos)
schreibe 0x04 : x01 -> x01  (wirkungslos)
schreibe 0x05 : x01 -> x01  (wirkungslos)
schreibe 0x06 : x01 -> x01  (wirkungslos)
schreibe 0x09 : x01 -> x01  (wirkungslos)
schreibe 0x0f : x01 -> x03  DP1     ✅
schreibe 0x10 : x03 -> x04  DP2     ✅
schreibe 0x11 : x04 -> x01  HDMI
```

Die Lesewerte wurden unabhängig davon verifiziert, indem am OSD manuell umgeschaltet
und `getvcp 60` im Sekundentakt mitprotokolliert wurde:

```
09:51:44  x04   ← DP2
09:52:21  x03   ← DP1   (manuell am OSD)
09:52:49  x04   ← DP2   (manuell zurück)
```

**Genau dieser Befund ist der Grund, warum `monitor-switch` Monitor-Profile hat.**
Eine Automatik, die sich auf den Capabilities-String verlässt, hätte hier keine
Chance.

## Fallstricke

**Der Capabilities-String lügt.** Für `0x60` deklariert der Monitor nur `01: VGA-1`
und `03: DVI-1` — weder die real funktionierenden Schreibwerte `0x0f`/`0x10` noch der
tatsächlich aktive Lesewert `0x04` stehen darin. Nicht auf diese Liste verlassen.

**Default-Timing ist zu schnell.** Ohne `--sleep-multiplier` bricht schon das Auslesen
der Capabilities mit „Maximum DDC retries exceeded" ab. Auf dem Raspberry Pi reichten
selbst 4 und 6 nicht — erst **8** trug. Für den Normalbetrieb (`getvcp`/`setvcp`)
genügt 4. (`--maxtries` akzeptiert maximal 15.)

**Writes sind träge.** Am Linux-Rechner wurde der erste Schreibversuch regelmäßig
verschluckt, eine Verify-und-Retry-Schleife über `getvcp 60` war Pflicht.

> Auf dem Raspberry Pi trat das in 6 Schaltvorgängen **kein einziges Mal** auf — jeder
> Write saß beim ersten Versuch. Die Retry-Schleife bleibt trotzdem im Code, sie
> kostet im Erfolgsfall nichts.

**Einstellungen gelten pro Eingang.** Die Helligkeit las `11`, während der Monitor
HDMI anzeigte, und `60` bei DisplayPort 2. Der Monitor führt für jeden Eingang einen
eigenen Satz Werte — **ein Eingangswechsel entwertet damit jeden anderen
zwischengespeicherten Wert**. `monitorctl` stößt deshalb bei jedem Wechsel der
Eingangsquelle eine vollständige Neulesung an.

Wissenswert, wenn man eigene Werkzeuge baut: eine Helligkeit, die nach dem Umschalten
falsch aussieht, ist kein Lesefehler, sondern schlicht eine andere Einstellung.

**Nie auf einen Eingang ohne Signal schalten.** Der gefährlichste Punkt, und der,
der die Architektur geprägt hat. Sobald der Monitor einen signallosen Eingang
*anzeigt*, hängt sich sein DDC-Motor auf: `0x37` bestätigt auf I²C-Ebene weiter, aber
jede DDC-Transaktion scheitert mit „DDC communication failed". Zweimal reproduziert.

`monitor-switch` begegnet dem mit dem `local_video`-Guard: bevor auf den eigenen
Eingang geschaltet wird, prüft der Dienst über `/sys/class/drm/`, dass sein Connector
`enabled` und `dpms On` ist.

> **Eine Gegenbeobachtung.** Der Monitor wurde auf einen DisplayPort-Eingang
> geschaltet, dessen Rechner ausgeschaltet war, blieb dort rund zwei Sekunden und
> wurde zurückgeschaltet. DDC arbeitete durchgehend weiter, die Lesungen danach waren
> sauber. Der Wedge tritt also nicht sofort ein, und kurze Berührung ist überstehbar —
> jedenfalls an diesem Monitor, in diesem einen Fall. Die ursprünglichen Wedges lagen
> beide auf dem HDMI-Steuerkanal und dauerten länger an.
>
> Das geschah versehentlich, nicht geplant, und wurde nicht wiederholt: herauszufinden,
> wo die Grenze liegt, hieße einen Zustand absichtlich herbeizuführen, aus dem nur das
> OSD wieder herausführt. Der Guard bleibt die Regel, das hier ist eine Fußnote und
> kein Freibrief.

**Wiederbelebung nach einem Wedge:** einen Link-Reset auf dem HDMI-Anschluss auslösen,
also HPD neu aussenden. Unter KDE Wayland:

```bash
kscreen-doctor output.HDMI-A-1.enable    # Signal auf HDMI legen, DDC kommt zurück
# ... jetzt per setvcp auf einen gültigen Eingang schalten ...
kscreen-doctor output.HDMI-A-1.disable
```

Alternativ am OSD manuell auf einen Eingang mit Signal wechseln. `xrandr` hilft unter
Wayland nicht — es erreicht nur Xwayland und scheitert mit `BadMatch`.

## Messungen auf dem Raspberry Pi Zero 2 W

Raspberry Pi OS Lite auf Debian 13 (Trixie), Kernel 6.18.39, `ddcutil` 2.2.0.

```
$ readlink -f /sys/class/drm/card0-HDMI-A-1/ddc
/sys/devices/platform/soc/3f805000.i2c/i2c-2

$ i2cdetect -y 2
30: 30 -- -- -- -- -- -- 37 -- -- 3a -- -- -- -- --     ← 0x37 antwortet
50: 50 -- -- -- 54 -- -- -- -- -- -- -- -- -- -- --

$ ddcutil detect
Display 1
   I2C bus:         /dev/i2c-2
   DRM connector:   card0-HDMI-A-1
   Model:           LC49G95T
   Product code:    28754  (0x7052)
   VCP version:     2.1
```

| Prüfung | Ergebnis |
|---|---|
| DDC-Bus | `/dev/i2c-2` — die Pi-3-Klassen-Annahme gilt auch unter Kernel 6.18 mit KMS |
| `0x37` | antwortet |
| `getvcp 60` | stabil über 5 aufeinanderfolgende Lesungen |
| ohne root | funktioniert, sofern der Benutzer in Gruppe `i2c` ist |
| Schalttest | 3 Runden DP2 ↔ DP1, **6 von 6 beim ersten Versuch** |

Alle Messungen liefen, während der Monitor DP2 anzeigte — die Annahme, dass DDC über
HDMI auch bei anderer aktiver Quelle trägt, ist damit auch auf dem Pi belegt.

### Laufzeiten

Bestimmen das Timeout-Budget der API:

| Operation | Dauer |
|---|---|
| `getvcp 60 --sleep-multiplier 4` | ~860 ms |
| `setvcp 60 --sleep-multiplier 4` | ~785 ms |
| `ddcutil detect` (warm) | ~24 ms |

Ein vollständiger Schaltvorgang mit einer Verify-Lesung liegt bei **~1,7 s**.

### Videosignal

Der DRM-Modus listete zunächst nur bis 1024×768 — der Monitor liefert über HDMI im
inaktiven Zustand offenbar nur eine Minimal-EDID. `video=HDMI-A-1:1920x1080@60D` in
`/boot/firmware/cmdline.txt` behob das: nach dem Reboot stand der Framebuffer auf
1920×1080, `0x37` antwortete weiterhin.

**Die Auflösung ist aber nicht deterministisch — und das wiegt weniger schwer, als
es aussieht.** Ein späterer Reboot kam mit derselben Kernel-Kommandozeile auf
1024×768 hoch. Der Grund steht im Log:

```
[drm] forcing HDMI-A-1 connector on
[drm] User-defined mode not supported: "1920x1080": 60 148500 …
```

und `/sys/class/drm/card0-HDMI-A-1/edid` war **0 Bytes** — der Monitor lieferte bei
diesem Boot gar keine EDID über HDMI. Ohne sie nimmt der Treiber den gewünschten
Modus nicht an und fällt auf eine Standardliste bis 1024×768 zurück.

Verlässlich ist der Teil, auf den es ankommt: **das `D` erzwingt den Connector
unabhängig von der EDID**, ein Signal liegt also immer an. Beide Boots hatten
`enabled`, `dpms On`, einen aktiven Framebuffer und einen `local_video`-Guard, der
`true` meldet. Unterschiedlich war allein die Pixelzahl — und für ein Gerät, dessen
Bild nur existiert, damit der Monitor nie einen toten Eingang zeigt, ist das
Kosmetik.

Ob der Monitor über HDMI eine EDID liefert, hängt offenbar von Zuständen ab, die wir
nicht steuern — derselbe Monitor tat es einmal und einmal nicht, bei gleicher
gewählter Quelle. Wer eine feste Auflösung braucht, kann per
`drm.edid_firmware=HDMI-A-1:edid/….bin` eine synthetische EDID unterschieben; aktuelle
Kernel liefern allerdings keine eingebauten EDID-Blobs mehr, die Datei muss man selbst
bereitstellen. Hier nicht erprobt.

## Capabilities-String

Vollständig ausgelesen mit `--sleep-multiplier 8 --maxtries 15,15,15`:

**Stufenlos:** `0x10` Helligkeit · `0x12` Kontrast · `0x62` Lautstärke ·
`0x16`/`0x18`/`0x1A` RGB-Gain · `0x6C`/`0x6E`/`0x70` RGB-Schwarzwert

**Auswahl:**

| VCP | Feature | Werte |
|---|---|---|
| `0x14` | Farbpreset | `01` sRGB · `04` 5000 K · `05` 6500 K · `06` 7500 K · `07` 8200 K · `08` 9300 K · `0a` 11500 K · `0b` User 1 |
| `0xDC` | Bildmodus | `00` Standard · `01` Produktivität · `02` Mixed · `03` Film · `04` Benutzerdefiniert |
| `0xD6` | Power | `01` On · `02` Standby · `04` Off |
| `0xCC` | OSD-Sprache | Deutsch, Englisch, Französisch, … |
| `0x8D` | Mute | — |
| `0x60` | Input Source | **`01: VGA-1`, `03: DVI-1` — beides falsch, siehe oben** |

**Nur lesen:** `0xC0` Betriebsstunden · `0xAC`/`0xAE` H/V-Frequenz ·
`0xB6` Display-Technologie · `0xC8` Controller-Typ · `0xC9` Firmware-Stand

Der Monitor meldet über HDMI und DisplayPort unterschiedliche EDIDs: Produktcode
`0x7052` (HDMI) gegenüber `0x7053` (DP), bei identischer Seriennummer.

## Verworfene Alternativen

| Variante | Bewertung |
|---|---|
| USB-Makropad am Linux-Rechner | verworfen — der Rechner läuft nicht durch |
| Mini-Dienst auf dem Linux-Rechner, extern getriggert | verworfen, gleicher Grund |
| ESP32 im HDMI-Port ([`hardwareddc`](https://github.com/TeaRex-coder/hardwareddc)) | verworfen — siehe unten |
| Raspberry Pi 4 mit Touchdisplay | verworfen — 3–5 W Leerlauf |
| **Raspberry Pi Zero 2 W, headless** | **gewählt** |

### Warum nicht der ESP

1. **Beschaffung.** HDMI-Breakout-Boards im 2,54-mm-Raster sind schlecht zu bekommen.
   Dazu die Pegelfrage: der ESP32-C3 ist nicht 5-V-tolerant.
2. **Der ESP liefert kein Videosignal.** Der HDMI-Eingang wäre ein dauerhaft toter
   Eingang geblieben — genau die Konstellation, die den DDC-Motor aufhängt. Die
   Firmware hätte diesen Fehlerfall auf ewig umschiffen müssen.

### Warum der Pi Zero 2 W

- **Er gibt ein echtes Videosignal aus.** Damit verschwindet die gefährlichste
  Fehlerklasse strukturell statt durch Disziplin in der Firmware.
- Kein Löten, kein Breakout, keine Pegelwandlung — ein Kabel.
- **0,4–0,7 W** im Leerlauf, gegenüber 3–5 W beim Pi 4.
- Der belegte HDMI-Port wird vom Opfer zum Gewinn: eine echte, nutzbare dritte Quelle.
- Bringt WLAN, ein Betriebssystem und damit Webservice plus Home-Assistant-Anbindung
  ohne Zusatzaufwand mit.

Erkaufte Nachteile: ein Betriebssystem, das gepflegt werden will, eine SD-Karte, die
altert, und Bootzeit statt Sofortbereitschaft.

## Anhang: DDC/CI auf Protokollebene

Wird für die gewählte Lösung nicht gebraucht — `ddcutil` erledigt das. Aufgehoben für
den Fall, dass doch einmal ein Mikrocontroller zum Einsatz kommt.
**Hergeleitet aus der Spezifikation, nicht am Gerät verifiziert.**

HDMI Typ A, die relevanten Pins:

| Pin | Signal |
|---|---|
| 15 | SCL |
| 16 | SDA |
| 17 | DDC-Masse |
| 18 | +5 V — kommt von der Quelle, versorgt die EDID-Logik der Senke |
| 19 | HPD — treibt der Monitor, für reines DDC nicht nötig |

I²C-Adresse `0x37` (8-Bit-Schreibadresse `0x6E`), maximal 100 kHz, mindestens 40 ms
Pause zwischen zwei Nachrichten. Nutzdaten für „Set VCP Feature":

```
0x51  0x84  0x03  0x60  <Wert-High>  <Wert-Low>  <Prüfsumme>
 │     │     │     │
 │     │     │     └── VCP-Code 0x60 (Input Source)
 │     │     └──────── Opcode „Set VCP Feature"
 │     └────────────── Länge: 0x80 | 4 Datenbytes
 └──────────────────── Quelladresse Host
```

Prüfsumme = XOR über **alle** Bytes einschließlich der Zieladresse `0x6E`:

| Ziel | Rahmen | Prüfsumme |
|---|---|---|
| DP1 (`0x0f`) | `6E 51 84 03 60 00 0F` | `0xD7` |
| DP2 (`0x10`) | `6E 51 84 03 60 00 10` | `0xC8` |

## Quellen

- [ddcutil #388 — Samsung Odyssey, Wechsel zwischen DP1 und DP2](https://github.com/rockowitz/ddcutil/issues/388)
- [ddcutil #398 — setvcp schlägt sporadisch fehl](https://github.com/rockowitz/ddcutil/issues/398)
- [MonitorControl #1580 — Samsung G9, DDC funktioniert nicht über DP](https://github.com/MonitorControl/MonitorControl/discussions/1580)
- [BetterDisplay #2498 — Unable to Change Input on Samsung Odyssey G9](https://github.com/waydabber/BetterDisplay/discussions/2498)
- [ddcutil — Raspberry Pi Dokumentation](https://www.ddcutil.com/raspberry/)
- [ddcutil #472 — Pi 4 „Display not found", auf Pi 3 funktionsfähig](https://github.com/rockowitz/ddcutil/issues/472)
- [TeaRex-coder/hardwareddc — ESP32-Platine für DDC über HDMI](https://github.com/TeaRex-coder/hardwareddc)
- [ddcutil Monitor Notes](https://www.ddcutil.com/archived/monitor_notes/)
