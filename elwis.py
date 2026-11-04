"""ELWIS-Tiefenatlas NOK: Bände auf der Seite vs. veröffentlichter Stand (nur Standardbibliothek, für CI).

    python elwis.py [--site URL]     # Exit 0: gleich, 1: neuer Stand (Markdown-Bericht auf stdout),
                                     #      2: Seite unlesbar, 3: Netzfehler (kein Issue, Lauf schlägt fehl)
"""
import argparse, html, json, re, sys, urllib.request

PAGE = "https://www.elwis.de/DE/Service/Tiefenatlas-BWaStr/Nord-Ostsee-Kanal/Nord-Ostsee-Kanal-node"
UA = {"User-Agent": "nok-tiefenkarte/1.0"}
SITE = "https://dermorz.github.io/nok-tiefenkarte/"
AUSGELASSEN = ("Flemhuder-See",)   # Bände, die nicht in die Karte kommen (eigener Erlaubnisschein, nicht gebraucht)


def names(text):
    """PDF-Namen (ohne .pdf) der Publikationslinks im Inhaltsteil der ELWIS-Seite (ohne Navigation/Archiv)."""
    content = text[text.find('id="content"'):]
    return [html.unescape(m).split("?")[0].rsplit("/", 1)[1]
            for m in re.findall(r'<a class="[^"]*Publication[^"]*" href="([^"]*)"', content)]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf-8")


def report(page, published):
    """Markdown-Bericht oder None, wenn gleich. page: Namen auf ELWIS, published: Namen im veröffentlichten Stand."""
    page = {n for n in page if not any(x in n for x in AUSGELASSEN)}
    neu, weg = sorted(page - published), sorted(published - page)
    if not neu and not weg:
        return None
    lines = [f"Auf [ELWIS]({PAGE}) hat sich der Tiefenatlas geändert.", ""]
    lines += ["**Neu:**"] + [f"- `{n}`" for n in neu] + [""] if neu else []
    lines += ["**Nicht mehr auf ELWIS (ersetzt/entfernt):**"] + [f"- `{n}`" for n in weg] + [""] if weg else []
    return "\n".join(lines + ["Ablauf: siehe #2."])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=SITE)
    a = ap.parse_args()
    try:
        text, idx = get(PAGE), json.loads(get(a.site.rstrip("/") + "/index.json"))
    except (OSError, ValueError) as e:          # Netz/HTTP/kaputtes JSON: kein falscher Alarm
        print(f"Abruf fehlgeschlagen: {e}", file=sys.stderr)
        sys.exit(3)
    found = names(text)
    if not found:
        print(f"Auf [ELWIS]({PAGE}) wurden keine PDF-Links gefunden – Seitenstruktur geändert? "
              "`elwis.names()` (und damit `make kmz`) anpassen.")
        sys.exit(2)
    published = {s["id"].rsplit("_p", 1)[0] for s in idx["sections"]}   # Abschnitt = PDF + Seite
    r = report(found, published)
    if r:
        print(r)
        sys.exit(1)
    print(f"unverändert: {len(published)} Bände")


if __name__ == "__main__":
    main()
