"""NOK-Tiefenatlas (ELWIS) -> georeferenzierte KMZ für Google Earth.

    python build.py            # laden, georeferenzieren, rastern, KMZ bauen
    python build.py --only NOK-74-76   # nur passende Bände (Debug)

Ausgabe in out/: nok-tiefenkarte.kmz, ggf. Teil-KMZs, report.md, preview/.
"""
import argparse, html, io, json, math, re, subprocess, sys, tempfile, zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pymupdf
import requests
from PIL import Image
from pyproj import Transformer
from scipy import interpolate, ndimage, optimize

Image.MAX_IMAGE_PIXELS = None
PAGE = "https://www.elwis.de/DE/Service/Tiefenatlas-BWaStr/Nord-Ostsee-Kanal/Nord-Ostsee-Kanal-node"
UA = {"User-Agent": "nok-tiefenkarte/1.0"}
PDF_DIR, OUT = Path("data/pdf"), Path("out")
PT = 0.0254 / 72            # m pro pt bei 1:1
DPI = 170                   # 1:2000 -> 0,30 m/px; Text bleibt bei 1:1000/1:3000 gleich lesbar
TILE = 4096                 # max. Kantenlänge je Overlay-Bild (GPU-Texturgrenze von Google Earth)
LICENSE = "Datenlizenz Deutschland – Zero – Version 2.0 (dl-de/zero-2-0)"
UTM = Transformer.from_crs(25832, 4326, always_xy=True)
TO_UTM = Transformer.from_crs(4326, 25832, always_xy=True)


# --------------------------------------------------------------------------- download
def fetch():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    page = requests.get(PAGE, headers=UA, timeout=60)
    page.raise_for_status()
    content = page.text[page.text.find('id="content"'):]  # ohne Navigation/Archiv-Teaser
    names = [html.unescape(m).split("?")[0].rsplit("/", 1)[1]
             for m in re.findall(r'<a class="[^"]*Publication[^"]*" href="([^"]*)"', content)]
    if not names:
        sys.exit("keine PDF-Links gefunden – Seitenstruktur geändert?")
    for old in PDF_DIR.glob("*.pdf"):
        if old.stem not in names:
            print("entferne veralteten Stand", old.name)
            old.unlink()
    for name in names:
        out = PDF_DIR / f"{name}.pdf"
        if out.exists():
            continue
        r = requests.get(f"{PAGE.rsplit('/', 1)[0]}/{name}.pdf?__blob=publicationFile", headers=UA, timeout=300)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            sys.exit(f"{name}: kein PDF")
        out.write_bytes(r.content)
        print(f"geladen {name} ({len(r.content) / 1e6:.1f} MB)")
    return sorted(PDF_DIR / f"{n}.pdf" for n in names)


# --------------------------------------------------------------------------- Plankopf
def num(s):
    return float(s.replace(",", "."))


def dms(s):
    m = re.fullmatch(r"(\d+)°(\d+)'(\d+,\d)\"", s)   # Eckwerte immer mit Zehntel; 54°0'0" ist Gradnetz
    return m and int(m[1]) + int(m[2]) / 60 + num(m[3]) / 3600


def title_block(text):
    """Metadaten aus dem Seitentext (Plankopf + Kopfzeile)."""
    g = lambda p: (m := re.search(p, text, re.I | re.S)) and m[1]
    km = re.search(r"km\s*(-?[\d,]+)\s*bis\s*km\s*(-?[\d,]+)", text, re.I)
    # Abschnittsname: Zeilen nach "Nord-Ostsee-Kanal" bis zur Peilungsart bzw. km-Angabe
    lines = []
    after = re.split(r"OSTSEE\s*\S?\s*KANAL[^\n]*\n", text, maxsplit=1, flags=re.I)
    for l in (after[1].split("\n") if len(after) > 1 else []):
        if re.search(r"peilung|\bkm\b.*bis", l, re.I):
            break
        l = re.sub(r"Messauftrags-|\bNr\.|Maßstab|1\s*:\s*\d+", "", l).strip()
        if l:
            lines.append(l)
    return dict(
        scale=int(g(r"Maßstab\s*1\s*:\s*(\d+)") or 0),
        rotation=g(r"Rotation\s*:\s*(-?[\d,]+)"),
        km=km and (num(km[1]), num(km[2])),
        date=g(r"ersten Messung:\s*([\d.]+\d)"),
        date_last=g(r"letzten Messung:\s*([\d.]+\d)"),
        section=" ".join(lines),
    )


# --------------------------------------------------------------------------- Passpunkte (Vektor)
def frame_of(page, drawings):
    W, H = page.rect.width, page.rect.height
    rects = [it[1] for d in drawings if d["type"] in ("s", "fs") for it in d["items"]
             if it[0] == "re" and it[1].width > 0.4 * W and it[1].height > 0.5 * H]
    return min(rects, key=lambda r: r.width * r.height)


def vector_controls(page):
    """Rahmen, Gitterticks (Position auf innerer Rahmenkante + Wert) und Eckkoordinaten."""
    drawings = page.get_drawings()
    fr = frame_of(page, drawings)
    x0, y0, x1, y1 = fr
    ticks = []  # (edge, px, py, outer_x, outer_y)
    for d in drawings:
        if d.get("color") not in ((0, 0, 0), (0.0, 0.0, 0.0)):
            continue
        for it in d["items"]:
            if it[0] != "l":
                continue
            a, b = it[1], it[2]
            if abs(a.x - b.x) < 0.05 and 2 < abs(a.y - b.y) < 8 and x0 + 1 < a.x < x1 - 1:
                lo, hi = sorted((a.y, b.y))
                if 2 < y0 - hi < 7:
                    ticks.append(("top", a.x, y0, a.x, lo))
                elif 2 < lo - y1 < 7:
                    ticks.append(("bottom", a.x, y1, a.x, hi))
            elif abs(a.y - b.y) < 0.05 and 2 < abs(a.x - b.x) < 8 and y0 + 1 < a.y < y1 - 1:
                lo, hi = sorted((a.x, b.x))
                if 2 < x0 - hi < 7:
                    ticks.append(("left", x0, a.y, lo, a.y))
                elif 2 < lo - x1 < 7:
                    ticks.append(("right", x1, a.y, hi, a.y))
    words = page.get_text("words")
    return (x0, y0, x1, y1), ticks, words, corners_from(words, (x0, y0, x1, y1))


def match_labels(ticks, words, m=None, max_d=16):
    """Gitterlabels eindeutig Ticks (edge, x, y, outer_x, outer_y) zuordnen, greedy nach Kosten:
    ohne Modell Abstand Label <-> Tickende (N-Labels oben stehen ~14 pt darüber), mit Modell das
    Residuum - das löst Vertauschungen bei eng benachbarten Ticks auf."""
    labels = [w for w in words if re.fullmatch(r"(32\d{6}|[56]\d{6})", w[4]) and w[4].endswith("00")]
    cands = []
    for i, t in enumerate(ticks):
        for j, w in enumerate(labels):
            d = math.hypot(max(w[0] - t[3], 0, t[3] - w[2]), max(w[1] - t[4], 0, t[4] - w[3]))
            if d > max_d:
                continue
            kind = "E" if w[4].startswith("32") else "N"
            g = dict(edge=t[0], x=t[1], y=t[2], kind=kind, value=float(w[4][2:] if kind == "E" else w[4]))
            cost = abs(m(g["x"], g["y"])[0 if kind == "E" else 1] - g["value"]) if m else d
            if m is None or cost < 1.5:
                cands.append((cost, i, j, g))
    used_t, used_l, gcps = set(), set(), []
    for _, i, j, g in sorted(cands, key=lambda c: c[0]):
        if i not in used_t and j not in used_l:
            used_t.add(i); used_l.add(j); gcps.append(g)
    return gcps


def corners_from(words, frame, parse=None):
    """Eckkoordinaten: Labels links -> Ecken TL/BL, oben -> TL/TR; Wert > 50 = Breite."""
    x0, y0, x1, y1 = frame
    corners = []
    for w in words:
        v = (parse or dms)(w[4])
        if not v:
            continue
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        if w[2] < x0 + 2:
            cxy = (x0, y0 if abs(cy - y0) < abs(cy - y1) else y1)
        elif w[3] < y0:
            cxy = (x0 if abs(cx - x0) < abs(cx - x1) else x1, y0)
        else:
            continue
        corners.append(dict(x=cxy[0], y=cxy[1], kind="lat" if v > 50 else "lon", value=v))
    return corners


# --------------------------------------------------------------------------- Ausgleichung
def model(p, s):
    th, c, f = p[:3]
    s = p[3] if len(p) > 3 else s     # Scan-Blätter: Maßstab mitschätzen
    a, b = s * math.cos(th), s * math.sin(th)
    return lambda x, y: (a * x + b * y + c, b * x - a * y + f)


def corner_residual(m, k):
    e, n = m(k["x"], k["y"])
    lon, lat = UTM.transform(e, n)
    if k["kind"] == "lat":
        return (lat - k["value"]) * 111_200
    return (lon - k["value"]) * 111_320 * math.cos(math.radians(lat))


def linear_init(gcps):
    """Freier Maßstab macht das Modell linear in (a, b, c, f): exakte Startwerte ohne Nebenminima."""
    A = [[g["x"], g["y"], 1, 0] if g["kind"] == "E" else [-g["y"], g["x"], 0, 1] for g in gcps]
    if len(A) < 4 or np.linalg.matrix_rank(np.array(A, float)) < 4:
        return None
    a, b, c, f = np.linalg.lstsq(np.array(A, float), [g["value"] for g in gcps], rcond=None)[0]
    return math.atan2(b, a), c, f, math.hypot(a, b)


def fit(gcps, corners, s, rot_deg, w_corner=0.1, free_scale=False):
    """E = a x + b y + c, N = b x - a y + f; a = s cosθ, b = s sinθ. Unbekannte θ, c, f (+ s bei Scans)."""
    def res(p, use):
        m = model(p, s)
        r = [(m(g["x"], g["y"])[0 if g["kind"] == "E" else 1] - g["value"]) for g in use]
        return r + [w_corner * corner_residual(m, k) for k in corners]
    use, dropped = list(gcps), []
    while True:  # robust: grobe Fehlzuordnungen (Label ↔ Tick, OCR) vor dem Feinfit entfernen
        p0 = linear_init(use)
        if p0 is None:
            break
        m = model(p0, s)
        r = np.array([m(g["x"], g["y"])[0 if g["kind"] == "E" else 1] - g["value"] for g in use])
        if np.abs(r).max() < 3 or len(use) <= 4:
            break
        dropped.append(use.pop(int(np.abs(r).argmax())))
    if p0 is None:  # zu wenige Ticks (z. B. nur eine Gitterrichtung): Start aus Eckpunkt + Plan-Rotation
        lat = next(k["value"] for k in corners if k["kind"] == "lat")
        lon = next(k["value"] for k in corners if k["kind"] == "lon")
        e0, n0 = TO_UTM.transform(lon, lat)
        x, y = next(k for k in corners if k["kind"] == "lat")["x"], next(k for k in corners if k["kind"] == "lat")["y"]
        cands = []
        for th in (math.radians(rot_deg), -math.radians(rot_deg)):
            a, b = s * math.cos(th), s * math.sin(th)
            cands.append((th, e0 - a * x - b * y, n0 - b * x + a * y, s))
    else:
        cands = [p0]
    best = min((optimize.least_squares(res, c[:4] if free_scale else c[:3], args=(use,)) for c in cands),
               key=lambda sol: sol.cost)
    for _ in range(5):  # Feinfit mit festem Maßstab, Ausreißer > 1 m entfernen
        r = np.array(res(best.x, use)[:len(use)])
        if not len(r) or np.abs(r).max() < 1.0:
            break
        dropped.append(use.pop(int(np.abs(r).argmax())))
        best = optimize.least_squares(res, best.x, args=(use,))
    m = model(best.x, s)
    r = np.array([m(g["x"], g["y"])[0 if g["kind"] == "E" else 1] - g["value"] for g in use])
    return dict(p=best.x.tolist(), gcps=use, dropped=dropped, res=r.tolist(),
                corner_res=[corner_residual(m, k) for k in corners])


def qa(f, corners):
    """OK: Tick-RMS < 0,3 m, Ecken < 2,5 m (0,1"-Rundung). Fehlt eine Gitterrichtung, stützt sie sich
    nur auf die Eckwerte -> Status 'OK (Ecken)', Lagegenauigkeit dann nur ~1–2 m in dieser Richtung."""
    n_e = sum(g["kind"] == "E" for g in f["gcps"]); n_n = len(f["gcps"]) - n_e
    rms = float(np.sqrt(np.mean(np.square(f["res"])))) if f["res"] else float("nan")
    cmax = float(np.abs(f["corner_res"]).max()) if f["corner_res"] else float("nan")
    kinds = {k["kind"] for k in corners}
    if not (rms < 0.3 and (cmax < 2.5 or not corners)):
        return rms, cmax, "PRÜFEN: Residuen/Ecken außerhalb Toleranz"
    if n_e >= 2 and n_n >= 1 and n_e + n_n >= 4:
        return rms, cmax, "OK"
    if (n_e >= 1 or "lon" in kinds) and (n_n >= 1 or "lat" in kinds) and len(corners) >= 3:
        return rms, cmax, "OK (Ecken)"
    return rms, cmax, "PRÜFEN: zu wenige Passpunkte"


# --------------------------------------------------------------------------- Tiefenfarben
# Die Bände haben fünf verschiedene Legenden (Kanal 8 Klassen, Weststrecke, Seen, Kiel, Obereider).
# Einheitlich: Tiefenflächen aus dem PDF weiß zeichnen (Linien/Zahlen bleiben), Tiefe aus den
# Tiefenkoten interpolieren und mit einer Skala neu einfärben. Die Klasse allein aus der Farbe zu
# bestimmen geht nicht: durch die Schummerung sind Kanal-Klassen zu ~38 % nicht unterscheidbar.
# Skala: 1-m-Stufen, Farbton von Rot (flach) über Grün nach Violett (tief), Helligkeit wechselt je Meter,
# damit auch benachbarte Stufen (Kolke, Rinnen) klar zu unterscheiden sind. (OKLCH, C 0,115, L 0,87/0,77)
# (Obergrenze der Stufe in m, Farbe)
DEPTH_SCALE = [(0, "ffb5b5"), (1, "f49980"), (2, "ffbf8c"), (3, "e4a75e"), (4, "f6cf78"), (5, "c2b75b"),
               (6, "ccdf87"), (7, "94c579"), (8, "99eaaf"), (9, "5fcca6"), (10, "6fedde"), (11, "41cad2"),
               (12, "70e7ff"), (13, "61c0f2"), (14, "9adaff"), (15, "93b2fe"), (16, "cacaff"), (None, "bfa3f3")]
PAL = np.array([[int(c[i:i + 2], 16) for i in (0, 2, 4)] for _, c in DEPTH_SCALE], np.float32)
EDGES = np.array([d for d, _ in DEPTH_SCALE[:-1]], np.float32)
N = r"(\d*\.?\d+)"
FILL = re.compile(rf"{N} {N} {N} (rg|scn)\s+{N} {N} {N} (RG|SCN)")    # Füll- = Strichfarbe (rg oder ICC-scn)


def legend_colors(page):
    """Grundfarben der Blattlegende: Farbspalte neben den 'x,xx m'-Labels unter 'Tiefe unter SKN'.
    None, wenn keine Legende im Text (gescannte Bände)."""
    W, H = page.rect.width, page.rect.height
    words = page.get_text("words")
    h = next((w for w in words if w[4] == "SKN" and w[0] > W * .75 and w[1] < H * .6), None)
    ms = [(w[1] + w[3]) / 2 for w in words if w[4] == "m"]
    labs = h and [w for w in words if re.fullmatch(r"-?\d+,\d\d", w[4]) and h[3] < w[1] < h[3] + 600
                  and h[0] - 140 < w[0] < h[0] and any(abs((w[1] + w[3]) / 2 - y) < 2 for y in ms)]
    if not labs:
        return None
    xr, yl = max(w[2] for w in labs), max(w[3] for w in labs)
    pix = page.get_pixmap(clip=pymupdf.Rect(xr + 20, h[3] + 2, xr + 40, yl + 80), dpi=144)
    runs = []
    for r in range(pix.height):
        c = pix.pixel(pix.width // 2, r)
        if runs and max(abs(a - b) for a, b in zip(c, runs[-1][1])) <= 2:
            runs[-1][0] += 1
        else:
            runs.append([1, c])
    skip = {(255, 255, 255), (0, 0, 0), runs[0][1]}          # erster Lauf: Hintergrund des Kastens
    return np.array(sorted({c for n, c in runs if n >= 5 and c not in skip}), np.float32)


def is_depth(rgb, base, tol=1.5):
    """Schummerung: Legendenfarbe b aufgehellt (b + t(255-b)) oder abgedunkelt (b(1+t))."""
    c, u = np.asarray(rgb, np.float32), 255 - base
    tl = np.clip(((c - base) * u).sum(1) / np.maximum((u * u).sum(1), 1e-9), 0, None)
    td = np.clip(((c - base) * base).sum(1) / (base * base).sum(1), None, 0)
    r = np.minimum(np.abs(base + tl[:, None] * u - c).max(1), np.abs(base * (1 + td[:, None]) - c).max(1))
    return bool(r.min() < tol)


def soundings(page):
    """Tiefenkoten: schwarze, waagerechte 'd,d', Lage = Mitte der Textbox (liegt auf dem Modellgitter)."""
    pts = []
    for b in page.get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            if abs(l["dir"][1]) > 0.01 or l["dir"][0] < 0:
                continue
            sp = [s for s in l["spans"] if s["color"] == 0]
            t = "".join(ch["c"] for s in sp for ch in s["chars"]).strip()
            if sp and re.fullmatch(r"-?\d{1,2},\d", t):
                bb = np.array([s["bbox"] for s in sp])
                pts.append(((bb[:, 0].min() + bb[:, 2].max()) / 2, (bb[:, 1].min() + bb[:, 3].max()) / 2,
                            float(t.replace(",", "."))))
    return np.array(pts).reshape(-1, 3)


def depth_variant(pdf, pno, base, rgb, out):
    """Einseitiges PDF, in dem alle Tiefenflächen die Farbe rgb haben. Liefert die Zahl ersetzter Farben."""
    d = pymupdf.open(pdf)
    d.select([pno - 1])
    p = d[0]
    xrefs = p.get_contents()
    s = p.read_contents().decode("latin1")
    memo, c = {}, "{} {} {}".format(*rgb)
    def sub(m):
        a = m.groups()
        if a[:3] != a[4:7]:
            return m.group(0)
        if a[:3] not in memo:
            memo[a[:3]] = is_depth([float(x) * 255 for x in a[:3]], base)
        return f"{c} {a[3]} {c} {a[7]}" if memo[a[:3]] else m.group(0)
    s = FILL.sub(sub, s)
    d.update_stream(xrefs[0], s.encode("latin1"))
    for x in xrefs[1:]:
        d.update_stream(x, b"")
    d.save(out)
    return sum(memo.values())


def ppm(pdf, pno, frame, k, out):
    x0, y0, x1, y1 = frame
    subprocess.run(["pdftoppm", "-f", str(pno), "-l", str(pno), "-r", str(72 * k),
                    "-x", str(int(x0 * k)), "-y", str(int(y0 * k)),
                    "-W", str(math.ceil((x1 - x0) * k)), "-H", str(math.ceil((y1 - y0) * k)),
                    "-png", "-singlefile", str(pdf), out], check=True)
    im = Image.open(out + ".png").convert("RGB")
    im.load()
    return im


def recolor(pdf, pno, frame, k, s, td):
    """Rahmen mit einheitlichen Tiefenfarben; None, wenn das Blatt keine Vektor-Legende/Koten hat."""
    page = pymupdf.open(pdf)[pno - 1]
    base, kot = legend_colors(page), soundings(page)
    if base is None or len(kot) < 10:
        return None
    if not depth_variant(pdf, pno, base, (1, 1, 1), f"{td}/w.pdf"):
        return None
    depth_variant(pdf, pno, base, (1, 0, 1), f"{td}/m.pdf")
    ox, oy = int(frame[0] * k) / k, int(frame[1] * k) / k
    px_m = s / k
    M = np.asarray(ppm(f"{td}/m.pdf", 1, frame, k, f"{td}/m"))
    mask = (M[..., 1] < 100) & (M[..., 0] > 150) & (M[..., 2] > 150)       # magenta = Tiefenfläche
    del M
    lab, n = ndimage.label(~mask)                                          # Löcher unter Zahlen/Linien
    mask |= np.r_[False, np.bincount(lab.ravel())[1:] * px_m ** 2 < 25][lab]
    del lab
    # Tiefe auf ~0,5-m-Gitter aus den Koten (linear, außerhalb der Hülle nächster Punkt)
    H, W = mask.shape
    f = max(1, round(0.5 / px_m))
    gy, gx = np.mgrid[0:H:f, 0:W:f]
    P = np.c_[(kot[:, 0] - ox) * k, (kot[:, 1] - oy) * k]
    dep = interpolate.LinearNDInterpolator(P, kot[:, 2])(gx, gy)
    nan = np.isnan(dep)
    dep[nan] = interpolate.NearestNDInterpolator(P, kot[:, 2])(gx[nan], gy[nan])
    dep = dep.astype(np.float32)
    # Schummerung, Licht von NW 45°: >0 aufhellen, <0 abdunkeln (wie im Original). Modell auf ~3 m
    # geglättet, sonst zeichnen sich die Dreiecke der Koten-Interpolation ab.
    dy, dx = np.gradient(-ndimage.gaussian_filter(dep, 3 / (f * px_m)), f * px_m)
    slope, aspect = np.arctan(np.hypot(dx, dy)), np.arctan2(dy, -dx)
    alt, az = math.radians(45), math.radians(315)
    hs = math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    shade = np.clip(hs - math.sin(alt), -0.12, 0.15).astype(np.float32)
    up = lambda a: np.asarray(Image.fromarray(a).resize((gx.shape[1] * f, gx.shape[0] * f), Image.BILINEAR))[:H, :W]
    dep, shade = up(dep), up(shade)
    out = np.array(ppm(f"{td}/w.pdf", 1, frame, k, f"{td}/w"))             # Linien auf Weiß
    for r in range(0, H, 512):                                             # zeilenweise: Speicher
        sl = slice(r, r + 512)
        c = PAL[np.searchsorted(EDGES, dep[sl], side="right")]
        t = shade[sl][..., None]
        c = np.where(t > 0, c + t * (255 - c), c * (1 + t))
        c = np.where(mask[sl][..., None], c, 255)
        out[sl] = (c * out[sl] / 255).astype(np.uint8)                     # multiplizieren
    return Image.fromarray(out)


def render(pdf, pno, frame, dpi, s):
    """Rahmen rendern; Vektorblätter mit einheitlichen Tiefenfarben (s = m pro pt)."""
    k = dpi / 72
    with tempfile.TemporaryDirectory() as td:
        im = recolor(pdf, pno, frame, k, s, td)
        if im is None:
            print(f"{Path(pdf).name} S. {pno}: Originalfarben (keine Vektor-Legende/Koten)", file=sys.stderr)
            im = ppm(pdf, pno, frame, k, f"{td}/p")
    return im, (int(frame[0] * k) / k, int(frame[1] * k) / k), k


def survey_mask(rgb, px_m):
    """Messfläche: farbig & hell, Linien der Basiskarte wegöffnen, Löcher (Zahlen) füllen."""
    a = rgb.astype(np.int16)
    mx, mn = a.max(2), a.min(2)
    sat = np.where(mx > 0, (mx - mn) * 255 // np.maximum(mx, 1), 0)
    m = (sat > 22) & (mx > 150)
    m = ndimage.binary_opening(m, iterations=4)
    m = ndimage.binary_closing(m, iterations=4)
    m = ndimage.binary_fill_holes(m)
    lab, n = ndimage.label(m)
    if n:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes >= (15 / px_m) ** 2   # < ~225 m² verwerfen
        m = keep[lab]
    m = ndimage.binary_fill_holes(m)
    dist = ndimage.distance_transform_edt(~m) * px_m           # m bis zur Fläche
    return np.clip((4.0 - dist) / 1.0, 0, 1)                   # 3 m dilatiert, 1 m weicher Rand


def georaster(pdf, pno, frame, s, p, res_m):
    """Rendert den Rahmen, maskiert und warpt nordausgerichtet auf ein Lon/Lat-Gitter.
    Pro Kachel (≤ TILE px) eine eigene Affine Ausgabepixel -> Seitenpixel, gefittet an exakt
    (pyproj) transformierten Punkten; so bleibt das Residuum auch bei langen Blättern klein."""
    im, (ox, oy), k = render(pdf, pno, frame, 2 * DPI, s)         # 2x überabtasten für den Warp
    small = np.asarray(im.resize((im.width // 2, im.height // 2), Image.BOX))
    alpha = survey_mask(small, s / (k / 2))
    alpha = Image.fromarray((alpha * 255).astype(np.uint8)).resize(im.size, Image.BILINEAR)
    rgba = Image.merge("RGBA", (*im.split(), alpha))
    del im, small
    th, c, f = p[:3]
    s = p[3] if len(p) > 3 else s
    A, B = s * math.cos(th), s * math.sin(th)
    x0, y0, x1, y1 = frame
    t = np.linspace(0, 1, 50)
    ex = np.r_[x0 + (x1 - x0) * t, x0 + (x1 - x0) * t, np.full(50, x0), np.full(50, x1)]
    ey = np.r_[np.full(50, y0), np.full(50, y1), y0 + (y1 - y0) * t, y0 + (y1 - y0) * t]
    lon, lat = UTM.transform(A * ex + B * ey + c, B * ex - A * ey + f)
    west, east, south, north = lon.min(), lon.max(), lat.min(), lat.max()
    mlon = 111_320 * math.cos(math.radians((north + south) / 2))
    dlon, dlat = res_m / mlon, res_m / 111_200
    W, H = math.ceil((east - west) / dlon), math.ceil((north - south) / dlat)
    nx, ny = math.ceil(W / TILE), math.ceil(H / TILE)
    out, worst = [], 0.0
    for j in range(ny):
        for i in range(nx):
            l, tp, r, bt = i * W // nx, j * H // ny, (i + 1) * W // nx, (j + 1) * H // ny
            U, V = np.meshgrid(np.linspace(0, r - l, 9), np.linspace(0, bt - tp, 9))
            U, V = U.ravel(), V.ravel()
            e, n = TO_UTM.transform(west + (l + U) * dlon, north - (tp + V) * dlat)
            # Inverse der Ähnlichkeitstransformation: [x, y] = M [E-c, N-f] / s², M = [[A, B], [B, -A]]
            px = (A * (e - c) + B * (n - f)) / s**2
            py = (B * (e - c) - A * (n - f)) / s**2
            X, Y = (px - ox) * k, (py - oy) * k                    # kontinuierliche Renderpixel
            G = np.c_[U, V, np.ones_like(U)]
            cx = np.linalg.lstsq(G, X, rcond=None)[0]
            cy = np.linalg.lstsq(G, Y, rcond=None)[0]
            worst = max(worst, float(np.hypot(G @ cx - X, G @ cy - Y).max() / k * s))
            tile = rgba.transform((r - l, bt - tp), Image.AFFINE, (*cx, *cy), Image.BILINEAR,
                                  fillcolor=(255, 255, 255, 0))
            bb = tile.getchannel("A").getbbox()
            if not bb:
                continue
            out.append((tile.crop(bb), dict(west=west + (l + bb[0]) * dlon, east=west + (l + bb[2]) * dlon,
                                            north=north - (tp + bb[1]) * dlat, south=north - (tp + bb[3]) * dlat)))
    box = dict(north=north, south=south, east=east, west=west)
    sc = min(1, 2400 / max(W, H))
    prev = Image.new("RGBA", (max(1, int(W * sc)), max(1, int(H * sc))), (60, 60, 60, 255))
    for tile, tb in out:
        tw = max(1, int(tile.width * sc)); thh = max(1, int(tile.height * sc))
        prev.alpha_composite(tile.resize((tw, thh)), (int((tb["west"] - west) / dlon * sc), int((north - tb["north"]) / dlat * sc)))
    return out, box, worst, (W, H), prev


def png256(img):
    q = img.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    buf = io.BytesIO()
    q.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# --------------------------------------------------------------------------- pro Blatt
def sheet_ids(pdfs):
    for pdf in pdfs:
        with pymupdf.open(pdf) as d:
            for i, pg in enumerate(d):
                if pg.rect.width * pg.rect.height > 841 * 600:   # Kartenblatt (Deckblätter sind A4)
                    yield str(pdf), i + 1


def process(job):
    try:
        return _process(job)
    except Exception as e:  # ein defektes Blatt soll den Lauf nicht abbrechen
        pdf, pno = job
        return dict(id=f"{Path(pdf).stem}_p{pno}", pdf=Path(pdf).name, page=pno, scale=0, rotation=None,
                    km=None, date=None, section="", status=f"FEHLER: {type(e).__name__}: {e}")


def _process(job):
    pdf, pno = job
    sid = f"{Path(pdf).stem}_p{pno}"
    cache = OUT / "sheets" / f"{sid}.json"
    newest = max(Path(pdf).stat().st_mtime, *(Path(__file__).with_name(n).stat().st_mtime for n in ("build.py", "scan.py")))
    if cache.exists() and cache.stat().st_mtime > newest:
        return json.loads(cache.read_text())
    page = pymupdf.open(pdf)[pno - 1]
    text = page.get_text()
    r = dict(id=sid, pdf=Path(pdf).name, page=pno, **title_block(text))
    if not page.get_drawings():
        from scan import scan_controls     # gescannte Bände: Passpunkte per OCR
        frame, ticks, words, corners, meta = scan_controls(pdf, pno)
        r.update({k: v for k, v in meta.items() if v}, source="scan")
    else:
        frame, ticks, words, corners = vector_controls(page)
        r["source"] = "vector"
    if not r["scale"]:
        r.update(status="FEHLER: kein Maßstab"); return save(cache, r)
    s = r["scale"] * PT
    gcps = match_labels(ticks, words)
    n_e = sum(g["kind"] == "E" for g in gcps); n_n = len(gcps) - n_e
    r.update(frame=list(map(float, frame)), n_e=n_e, n_n=n_n, n_corner=len(corners))
    if len(gcps) + len(corners) < 3:
        r.update(status="FEHLER: zu wenige Passpunkte"); return save(cache, r)
    scanned = r["source"] == "scan"
    f = fit(gcps, corners, s, num(r["rotation"]) if r["rotation"] else 0, free_scale=scanned)
    gcps = match_labels(ticks, words, m=model(f["p"], s))          # Zuordnung mit Modell verfeinern
    if len(gcps) >= 2:
        f = fit(gcps, corners, s, num(r["rotation"]) if r["rotation"] else 0, free_scale=scanned)
    rms, cmax, status = qa(f, corners)
    r.update(theta=math.degrees(f["p"][0]) % 360, p=f["p"], rms=rms, res_max=float(np.abs(f["res"]).max()),
             corner_max=cmax, dropped=len(f["dropped"]), n_used=len(f["gcps"]),
             n_e_used=sum(g["kind"] == "E" for g in f["gcps"]), n_n_used=sum(g["kind"] == "N" for g in f["gcps"]),
             scale_fit=f["p"][3] / s if scanned else 1.0, status=status)
    if not status.startswith("OK"):
        return save(cache, r)
    if scanned and abs(r["scale_fit"] - 1) > 0.003:
        r.update(status=f"PRÜFEN: Scan-Maßstab weicht ab ({r['scale_fit']:.4f})"); return save(cache, r)
    tiles_, box, aff, size, prev = georaster(pdf, pno, frame, s, f["p"], res_m=s * 72 / DPI)
    r.update(box=box, aff_res=aff, size=size)
    if aff > 0.2:
        r.update(status="PRÜFEN: Affin-Residuum > 0,2 m"); return save(cache, r)
    tdir = OUT / "sheets" / sid
    tdir.mkdir(parents=True, exist_ok=True)
    for old in tdir.glob("*.png"):
        old.unlink()
    r["tiles"] = []
    for i, (t, tb) in enumerate(tiles_):
        fn = tdir / f"{i}.png"
        fn.write_bytes(png256(t))
        r["tiles"].append(dict(file=str(fn), **tb))
    (OUT / "preview").mkdir(exist_ok=True)
    prev.convert("RGB").save(OUT / "preview" / f"{sid}.jpg", quality=85)
    return save(cache, r)


def save(cache, r):
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(r, ensure_ascii=False, indent=1))
    return r


# --------------------------------------------------------------------------- KMZ
def folder_of(r):
    if not re.search(r"NOK-\d", r["pdf"]):         # Seen, Häfen, Werft, Zufahrten
        return "Seen und Häfen"
    sec = r["section"].lower()
    west = "west" in sec or ("ost" not in sec and r["km"] and r["km"][0] < 50)
    return "Weststrecke" if west else "Oststrecke"


def band_name(pdf):
    stem = Path(pdf).stem.split("-", 1)[1]
    return stem.replace("-", " ").replace("ae", "ä").replace("ue", "ü").replace("oe", "ö")


def name_of(r):
    sec = r["section"] or band_name(r["pdf"])
    if folder_of(r) == "Seen und Häfen":            # Ortsname fehlt im Plankopf teils (Brunsbüttel)
        norm = lambda t: t.lower().replace("ä", "ae").replace("ü", "ue").replace("ö", "oe")
        if not any(w in norm(sec) for w in re.findall(r"[a-z]{4,}", norm(band_name(r["pdf"])))):
            sec = f"{band_name(r['pdf'])} – {sec}"
    fmt = lambda v: f"{v:g}".replace(".", ",").replace("-", "−")
    km = f" km {fmt(r['km'][0])}–{fmt(r['km'][1])}" if r["km"] else ""
    return f"{sec}{km} (Messung {r['date']})"


def kml_overlay(name, href, b, desc, draw):
    return (f"<GroundOverlay><name>{html.escape(name)}</name><description><![CDATA[{desc}]]></description>"
            f"<drawOrder>{draw}</drawOrder><Icon><href>{href}</href></Icon><LatLonBox>"
            f"<north>{b['north']:.8f}</north><south>{b['south']:.8f}</south>"
            f"<east>{b['east']:.8f}</east><west>{b['west']:.8f}</west></LatLonBox></GroundOverlay>")


def write_kmz(path, title, sheets):
    folders = {}
    for r in sorted(sheets, key=lambda r: (r["km"] or (999, 0))[0]):
        name = name_of(r)
        desc = (f"<b>{html.escape(name)}</b><br>Quelle: ELWIS Tiefenatlas Nord-Ostsee-Kanal, "
                f"Wasserstraßen- und Schifffahrtsamt Elbe-Nordsee – <a href='{PAGE}'>{PAGE}</a><br>"
                f"Band: {r['pdf']} (Seite {r['page']}), Maßstab 1:{r['scale']}, "
                f"Messung {r['date']}{' – ' + r['date_last'] if r.get('date_last') and r['date_last'] != r['date'] else ''}<br>"
                f"Lizenz: {LICENSE}<br>Georeferenzierung: RMS {r['rms']:.2f} m an {r['n_used']} Gitterticks, "
                f"Ecken max. {r['corner_max']:.1f} m. Nicht zur Navigation.")
        parts = [kml_overlay(name if len(r["tiles"]) == 1 else f"{name} [{i + 1}]",
                             f"files/{r['id']}/{i}.png", t, desc, 1)
                 for i, t in enumerate(r["tiles"])]
        body = parts[0] if len(parts) == 1 else f"<Folder><name>{html.escape(name)}</name>{''.join(parts)}</Folder>"
        folders.setdefault(folder_of(r), []).append(body)
    order = ["Weststrecke", "Oststrecke", "Seen und Häfen"]
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f"<name>{html.escape(title)}</name><description><![CDATA[Quelle: ELWIS ({PAGE}); Lizenz: {LICENSE}]]></description>"
           + "".join(f"<Folder><name>{k}</name>{''.join(folders[k])}</Folder>" for k in order if k in folders)
           + "</Document></kml>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:   # PNGs sind schon komprimiert
        z.writestr(zipfile.ZipInfo("doc.kml"), kml.encode(), zipfile.ZIP_DEFLATED)
        for r in sheets:
            for i, t in enumerate(r["tiles"]):
                z.write(t["file"], f"files/{r['id']}/{i}.png")
    return path.stat().st_size


def report(rows):
    f = lambda v, d=2: "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{d}f}"
    out = ["| Blatt | Abschnitt | km | Messung | Maßstab | Rotation (Plan/Fit) | Ticks E/N (verw.) | RMS m | max m | Ecken max m | Affin m | Status |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (folder_of(r), (r["km"] or (999, 0))[0])):
        km = f"{r['km'][0]:g}–{r['km'][1]:g}".replace(".", ",") if r["km"] else "–"
        out.append(f"| {r['id']} | {r['section']} | {km} | {r['date'] or '–'} | 1:{r['scale']} | "
                   f"{r['rotation'] or '–'}° / {f(r.get('theta'), 1)}° | {r.get('n_e', 0)}/{r.get('n_n', 0)} ({r.get('n_used', '–')}) | "
                   f"{f(r.get('rms'))} | {f(r.get('res_max'))} | {f(r.get('corner_max'), 1)} | {f(r.get('aff_res'), 3)} | {r['status']} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Teilstring des Bandnamens")
    ap.add_argument("--offline", action="store_true", help="nicht neu laden")
    ap.add_argument("-j", type=int, default=4, help="parallele Blätter (RAM: ~3 GB je Blatt)")
    a = ap.parse_args()
    pdfs = sorted(PDF_DIR.glob("*.pdf")) if a.offline else fetch()
    jobs = [j for j in sheet_ids(pdfs) if not a.only or a.only in j[0]]
    with ProcessPoolExecutor(a.j) as ex:
        rows = list(ex.map(process, jobs))
    for r in rows:
        print(f"{r['id']:40s} {r['status']}  rms={r.get('rms', float('nan')):.2f} ecken={r.get('corner_max', float('nan')):.1f}")
    (OUT / "report.md").write_text(report(rows) + "\n")
    if a.only:
        return
    ok = [r for r in rows if r["status"].startswith("OK")]
    size = write_kmz(OUT / "nok-tiefenkarte.kmz", "NOK Tiefenatlas (ELWIS)", ok)
    print(f"\nnok-tiefenkarte.kmz: {size / 1e6:.1f} MB, {len(ok)}/{len(rows)} Blätter")
    if size > 100e6:  # zusätzlich nach Abschnitten aufteilen
        for k in ("Weststrecke", "Oststrecke", "Seen und Häfen"):
            part = [r for r in ok if folder_of(r) == k]
            fn = OUT / f"nok-tiefenkarte-{k.split()[0].lower()}.kmz"
            print(f"{fn.name}: {write_kmz(fn, f'NOK Tiefenatlas – {k}', part) / 1e6:.1f} MB")
    bad = [r for r in rows if not r["status"].startswith("OK")]
    if bad:
        print("\nNicht übernommen:", *(f"  {r['id']}: {r['status']}" for r in bad), sep="\n")


if __name__ == "__main__":
    main()
