# Plan

Stand: 03.11.2026. Später als GitHub-Issues anlegen.

## Jetzt
- [x] Uferlinien für NOK-80-82 und NOK-82-83: andere Zeichenvorlage (Ufer petrol, 1,41 pt), ergänzt
- [x] Vollausbau: 49 Blätter, 33 752 Kacheln, 354 MB. Linienversatz benachbarter Blätter Median 0,32 m,
      max. 1,3 m (82-83/83-86 und 79-80/80-82: andere Zeichenvorlage, Abgleich über Uferlinien 0,1–0,2 m)
- [x] Tiefenkoten entfernt: Karten sind reine Bildlayer
- [x] Tiefenfarben vereinheitlicht: 1-m-Stufen 0–16 m für alle Vektorblätter (auch zweite Zeichenvorlage
      mit ICC-Farben), kontrastreiche Skala mit wechselnder Helligkeit, Legende im Info-Dialog
- [ ] Hosting auf GitHub Pages (Repo `nok-tiefenkarte`): erst nach Freigabe anlegen und veröffentlichen

## Später
- [ ] Angel-Sperrzonen nachschärfen (`rules.yaml`, macht der Nutzer):
  - noch nicht kartiert: Betriebs-/Ölhafen Brunsbüttel; Gieselaukanal, Audorfer See, Flemhuder See,
    Achterwehrer Kanal (Grenzpunkte von Hand); Kiel-Holtenau (Olympiabrücke–Schleuse)
  - Anlegebrücken und Umschlagstellen digitalisieren (bisher nur Fähren aus OSM, Puffer 50 m prüfen)
  - Mündung der Borgstedter Enge: ~80 m Südufer zählen als NOK (grün) – soll die Enge-Regel gelten?
  - Flemhuder See, Zufahrt Obereider: Band verläuft Nord–Süd, Nord/Süd-Zuordnung prüfen
- [x] Gescannte Bände (NOK-37-39, NOK-86-88): Tiefenkoten per Ziffern-Vorlagen aus NOK-88-91 gelesen (`scan.py`),
      gleiche Farbskala; Uferlinie/Achse aus den Pixelfarben, km an den Nachbarblättern verankert (`ufer.py`).
      Einzelne Fehllesungen möglich (kleine Farbflecken)
- [x] Angeln, Abgleich mit der hejfish-Gewässerkarte (https://www.hejfish.com/d/12543-nord-ostsee-kanal, nur
      als Vergleich, Geometrie nicht übernommen): Fährbuchten ± 90 m, Stege, Hafen-/Werftflächen und Häfen
      Brunsbüttel aus OSM. Rote hejfish-Strecken im Geltungsbereich zu 74 % abgedeckt.
- [ ] Angeln, Rest-Abweichungen zu hejfish (prüfen, ob der Schein das hergibt):
  - bei hejfish rot, bei uns nicht: Brunsbüttel Süd km 1,7–2,4 (Schleuse/Fähre); km 85,55–85,68 Süd
  - laut hejfish-Seitentext gesperrt bis zur Instandsetzung: barrierefreier Angelplatz Weiche Kudensee
    und Oldenbüttel (Gieselau-Mündung) – fehlt in `rules.yaml`
- [x] Stege nur als Bauwerk rot (eigene OSM-Linie), Ufer davor grün; Stege in roten Hafenflächen nicht extra
- [x] Dückerswisch: ganze westliche Ausbuchtung bis km 20,98 (statt Schein 20,45–20,80), Kanalseite der Mole frei
- [x] Gieselaukanal orange („Eigener Erlaubnisschein nötig“, wie hejfish)
- [x] Extra-Uferlinien aus OSM: Rendsburger Hafen, Westufer Obereider, Schirnau Nord km 70,18–70,74
- [x] Abgeschnittene Tiefenkoten am Blattrand („11,1“ -> „1,1“) verworfen (`build.drop_cut`)
- [ ] Update-Ablauf bei neuem ELWIS-Stand: `make all`, neu veröffentlichen; App bietet für offline
      gespeicherte Abschnitte „Aktualisieren“ an. Ablauf dokumentieren/automatisieren
      (z. B. regelmäßiger Check der ELWIS-Seite auf neue Bände).

## Vielleicht
- [ ] Tiefenzahlen per Schalter ein-/ausblenden: Koten aus dem PDF entfernen, eigene transparente
      Kachelebene nur mit den Zahlen (Scans: Zahlen im Bild, dort nicht ohne Weiteres)

## Zuletzt
- [ ] Dunkelmodus überarbeiten (Schalter Automatisch/Hell/Dunkel unter „Abschnitte“ ist da): Karte wird derzeit invertiert (Tiefenfarben werden dunkel).
      Alternative: Farben behalten, nur abdunkeln. Entscheidung mit Screenshots.
      Mit der einheitlichen Legende passt die invertierte Karte nicht mehr zur Legende.
