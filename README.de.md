<div align="center">

# monitor-switch

**Die Eingangsquelle deines Monitors per Tastendruck wechseln — von einem Raspberry
Pi aus, der immer läuft.**

Ein kleines Dauergerät hängt am HDMI-Eingang des Monitors, spricht DDC/CI und stellt
alles, was der Monitor kann, über HTTP, eine Weboberfläche und Home Assistant bereit.

[English version](README.md) · [Messprotokolle](docs/hardware-findings.de.md) ·
[Monitor-Profil schreiben](docs/profiles.md)

</div>

---

> **Status: benutzbar, noch nicht veröffentlicht.**
> Alles läuft und ist auf echter Hardware verifiziert — ein Samsung Odyssey G9 an
> einem Raspberry Pi Zero 2 W, die Home-Assistant-Anbindung eingeschlossen. Nicht
> erprobt ist bisher jeder *andere* Monitor. [`docs/status.md`](docs/status.md)
> sagt genau, was belegt ist und was nicht.

## Das Problem

Zwei Rechner teilen sich einen Monitor. Umschalten heißt: mit dem winzigen Joystick
hinter dem Panel ins OSD-Menü tauchen. Jedes Mal.

Die naheliegende Lösung ist DDC/CI — ein Standard, mit dem Software dem Monitor sagen
kann, er möge den Eingang wechseln. Nur:

- **Bei vielen Monitoren funktioniert DDC/CI über DisplayPort schlicht nicht.** Beim
  Samsung Odyssey G9, um den herum dieses Projekt entstand, antwortet der DDC-Slave
  über DP überhaupt nicht. Nur HDMI trägt.
- **Man kann nicht von einem Rechner *weg*schalten, der aus ist.** Zeigt der Monitor
  Rechner A und Rechner B schläft, hilft keiner von beiden.
- **Monitore lügen über ihre eigenen Fähigkeiten.** Der G9 meldet Werte für die
  Eingangsquelle, die schlicht falsch sind — und seine Lesewerte unterscheiden sich
  von seinen Schreibwerten.

## Die Lösung

Einen **Raspberry Pi Zero 2 W an den HDMI-Eingang des Monitors** hängen. Er braucht
0,4–0,7 W, kostet fast nichts und ist völlig unabhängig von den Rechnern, zwischen
denen er umschaltet.

Weil der Pi ein echtes Videosignal ausgibt, ist der HDMI-Port kein Opfer mehr, sondern
eine echte dritte Quelle — und der gefährlichste DDC-Fehlerfall (ein Monitor, der
einen signallosen Eingang anzeigt, hängt seinen DDC-Motor auf) verschwindet
strukturell.

```
   ┌──────────┐  DP1
   │ Rechner A├──────────┐
   └──────────┘          │      ┌─────────┐
                         ├──────┤ Monitor │
   ┌──────────┐  DP2     │      └────┬────┘
   │ Rechner B├──────────┘           │ HDMI  ← DDC/CI-Steuerkanal
   └──────────┘                      │         (und echte dritte Quelle)
                              ┌──────┴──────┐
                              │  Pi Zero 2W │  monitor-switch
                              └─────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
        Weboberfläche            HTTP-API             Home Assistant
      (jeder Browser)      (Tastenkürzel, Skripte)        (MQTT)
```

![Die Weboberfläche von monitor-switch: Kacheln für die Eingangsquellen mit hervorgehobener aktiver Quelle, Regler für Helligkeit, Kontrast und Lautstärke, darunter eine Zeile mit Nur-Lese-Werten des Monitors](docs/images/ui.png)

## Was es kann

- **Eingang umschalten** per Tastenkürzel, Browser, Handy oder Home-Assistant-Dashboard
  — unabhängig davon, welcher Rechner gerade läuft
- **Alles andere steuern, was der Monitor hergibt**: Helligkeit, Kontrast, Lautstärke,
  Mute, Bildmodus, Farbtemperatur, RGB-Gain und -Schwarzwert
- **Auslesen, was der Monitor über sich weiß**: Betriebsstunden, Firmware-Stand,
  Frequenzen, Power-Zustand
- **Funktioniert mit jedem DDC/CI-Monitor**, nicht nur mit dem, für den es gebaut
  wurde — jeder gelesene und geschriebene Wert steht in einem Profil, das du
  anpassen kannst
- **Kommt mit lügenden Monitoren klar** — Profile überschreiben die Auto-Erkennung
  dort, wo der Capabilities-String falsch liegt
- **Lässt dich nie vor einem schwarzen Bild stehen** — ein Guard verweigert das
  Schalten auf den Pi-Eingang, solange der Pi nicht nachweislich Bild ausgibt

## Schnellstart

Du brauchst einen Raspberry Pi (jedes Modell mit HDMI) mit Raspberry Pi OS,
angeschlossen am HDMI-Eingang deines Monitors, per SSH erreichbar.

```bash
git clone https://github.com/DimpiM/monitor-switch.git
cd monitor-switch/ansible

cp inventory.example.ini inventory.ini
cp group_vars/all.example.yml group_vars/all.yml
# beide anpassen: Adresse deines Pi, und welche Eingänge du bereitstellen willst

ansible-playbook -i inventory.ini site.yml
```

Danach `http://<dein-pi>:8765/` im Browser öffnen.

Das Playbook installiert die Pakete, richtet I²C ein, erzwingt einen stabilen
Videomodus, rollt den Dienst aus — und bricht ab, wenn die Health-Prüfung nicht
antwortet.

## Funktioniert mein Monitor?

Auf dem Pi ausführen, sobald er angeschlossen ist:

```bash
sudo apt install -y ddcutil i2c-tools
BUS=$(basename "$(readlink -f /sys/class/drm/card*-HDMI-A-1/ddc)" | sed 's/i2c-//')
sudo i2cdetect -y "$BUS" | grep '^30:'
```

Erscheint in dieser Zeile eine `37`, spricht dein Monitor DDC/CI und alles Weitere
kann kommen. Tauchen nur `30` und `50` auf, liefert der Monitor zwar eine EDID, aber
kein DDC/CI auf diesem Anschluss — andere Eingänge probieren, oder ein anderes Kabel.

Einzelheiten und Fehlerbilder: [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Monitor-Profile

Die Auto-Erkennung liest den Capabilities-String des Monitors und baut daraus die
Feature-Liste. Für wohlerzogene Monitore reicht das.

Für den Samsung Odyssey G9 reicht es **nicht**: der deklariert Werte für die
Eingangsquelle, die es nicht gibt, und verschweigt die, die funktionieren. Profile
dürfen deshalb alles überschreiben:

```yaml
match: { mfg: SAM, model: LC49G95T }
name: Samsung Odyssey G9
features:
  input_source:
    vcp: 0x60
    type: select
    options:
      # dieser Monitor meldet andere Werte zurück, als er annimmt
      - { id: dp1,  label: DisplayPort 1, write: 0x0f, read: 0x03 }
      - { id: dp2,  label: DisplayPort 2, write: 0x10, read: 0x04 }
      - { id: hdmi, label: HDMI,          write: 0x11, read: 0x01,
          guard: local_video }
```

Das passende Profil wird anhand von Hersteller und Modell aus der EDID automatisch
gewählt. Braucht dein Monitor eins, führt dich das `probe`-Kommando sicher durch die
Wertermittlung — es schaltet automatisch zurück, wenn du nicht bestätigst. Ein
Fehlgriff kann dich also nicht aussperren.

**Ein Profil für deinen Monitor beizusteuern ist das Nützlichste, was du für dieses
Projekt tun kannst.**

Vollständige Anleitung: [`docs/profiles.md`](docs/profiles.md).

## Home Assistant

Der Dienst meldet sich per MQTT Discovery an. Jede Steuerung wird zur Entity — ein
Dropdown für die Eingangsquelle, Regler für Helligkeit und Lautstärke, Sensoren für
die Nur-Lese-Werte. Der Zustand bleibt synchron, weil der Dienst den Monitor abfragt
und sich nicht auf seinen eigenen letzten Befehl verlässt.

Einrichtung: [`docs/home-assistant.md`](docs/home-assistant.md).

## Hardware-Hinweise

| Teil | Anmerkung |
|---|---|
| Raspberry Pi Zero 2 W | Jeder Pi geht; der Zero 2 W wurde wegen 0,4–0,7 W Leerlauf gewählt |
| **Kabel Mini-HDMI (Typ C) → HDMI (Typ A)** | **Der klassische Fehlkauf.** Die Zero-Familie hat *Mini*-HDMI. *Micro*-HDMI (Typ D) sitzt am Pi 4 und Pi 5. Sie sehen sich ähnlich und passen nicht zueinander. |
| Netzteil | Am **PWR**-Anschluss, nicht am USB-Datenport |
| microSD | Class 10 genügt |

## Sicherheit

Es gibt keine Authentifizierung. Der Dienst ist für ein vertrauenswürdiges LAN gedacht
und bindet an eine konfigurierbare Adresse — standardmäßig **nicht** an `0.0.0.0`.
Nicht ins Internet stellen.

## Dokumentation

| | |
|---|---|
| [Messprotokolle](docs/hardware-findings.de.md) | Jede Messung, jeder Fallstrick, und warum das Design so aussieht |
| [Monitor-Profile](docs/profiles.md) | Profil schreiben und beisteuern |
| [Home Assistant](docs/home-assistant.md) | MQTT-Discovery einrichten |
| [Fehlersuche](docs/troubleshooting.md) | Wenn DDC sich danebenbenimmt |
| [Projektstand](docs/status.md) | Was auf Hardware belegt ist — und was nicht |

## Dank

Baut auf [`ddcutil`](https://www.ddcutil.com/) von Sanford Rockowitz auf, das die
eigentliche DDC/CI-Arbeit erledigt.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
