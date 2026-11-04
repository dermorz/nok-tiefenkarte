"""Passpunkte für Bände, deren Kartenblatt nur als Bild (JPEG) im PDF liegt: Rahmen und Ticks aus
Pixeln, Gitterlabels/Eckwerte/Plankopf per Tesseract-OCR. Gleiches Blattlayout wie die Vektorbände."""
import re, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

from build import corners_from, title_block

Image.MAX_IMAGE_PIXELS = None
BAR = 4.32          # pt zwischen äußerer Rahmenlinie und innerer Kante (= Ticklänge)


def runs(mask_1d):
    """[(start, end_exkl)] zusammenhängender True-Bereiche."""
    d = np.diff(np.r_[0, mask_1d.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def frame_lines(prof, length, k):
    """Innere Rahmenlinie + äußere dünne Linie im Abstand BAR (vorne/hinten)."""
    rr = runs(prof > 0.7 * length)       # Strichelbalken (~50 %) fällt raus
    mid = [((a + b) / 2, b - a) for a, b in rr]
    first = last = None
    for c, w in mid:                      # dicke innere Linie, dünne äußere im Abstand ~BAR
        for c2, w2 in mid:
            if w2 < w and w >= 4 and BAR * k <= abs(c - c2) <= BAR * k + w + 4:
                if c2 < c and not first:
                    first = (c, c2)
                if c2 > c:
                    last = (c, c2)
    return first, last, rr


def ocr(img, box, scale=2, psm=11):
    """Tesseract-Wörter als (x0, y0, x1, y1, text) in Bildpixeln."""
    crop = img.crop(box).reduce(scale)
    with tempfile.NamedTemporaryFile(suffix=".png") as t:
        crop.save(t.name)
        out = subprocess.run(["tesseract", t.name, "-", "-l", "afr", "--psm", str(psm), "tsv"],
                             capture_output=True, text=True, check=True).stdout
    words = []
    for line in out.splitlines()[1:]:
        c = line.split("\t")
        if len(c) == 12 and c[11].strip():
            l, t_, w, h = (int(v) * scale for v in c[6:10])
            words.append((box[0] + l, box[1] + t_, box[0] + l + w, box[1] + t_ + h, c[11].strip()))
    return words


def ocr_text(img, box):
    crop = img.crop(box).reduce(2)
    with tempfile.NamedTemporaryFile(suffix=".png") as t:
        crop.save(t.name)
        return subprocess.run(["tesseract", t.name, "-", "-l", "afr", "--psm", "4"],
                              capture_output=True, text=True, check=True).stdout


def dms_ocr(s):
    """OCR-tolerant für Eckwerte wie 54°9'46,4". Tesseract liest '°' als 7, *, % oder gar nicht und
    verliert teils das '. Grad über bekannte Präfixe (NOK: 53–54° N, 9–10° E), Zehntel über das Komma;
    ohne ' nur eindeutige Ziffernzahlen (mmss / ms). Mehrdeutiges -> None (Ecke fällt weg)."""
    m = re.fullmatch(r"(54|53|10|9)(.*?),(\d)\"?", s)
    if not m:
        return None
    body = m[2]
    if "'" in body:
        mins, secs = body.rsplit("'", 1)
        mins = re.sub(r"\D", "", mins)
        mins = mins[1:] if len(mins) == 3 else mins            # als Ziffer gelesenes '°'
    else:
        d = re.sub(r"^\D", "", body)
        if not d.isdigit() or len(d) not in (2, 4):
            return None
        mins, secs = d[:len(d) // 2], d[len(d) // 2:]
    if not (mins.isdigit() and secs.isdigit() and 1 <= len(mins) <= 2 and 1 <= len(secs) <= 2):
        return None
    if int(mins) > 59 or int(secs) > 59:
        return None
    return int(m[1]) + int(mins) / 60 + (int(secs) + int(m[3]) / 10) / 3600


def scan_controls(pdf, pno):
    doc = pymupdf.open(pdf)
    page = doc[pno - 1]
    info = page.get_image_info(xrefs=True)[0]
    img = Image.open(__import__("io").BytesIO(doc.extract_image(info["xref"])["image"])).convert("L")
    bx0, by0, bx1, by1 = info["bbox"]
    k = img.width / (bx1 - bx0)                 # px pro pt
    to_pt = lambda x, y: (bx0 + x / k, by0 + y / k)
    a = np.asarray(img) < 110
    H, W = a.shape
    top, bottom, rows = frame_lines(a.sum(1), W, k)
    left, _, cols = frame_lines(a.sum(0), H, k)
    if not (top and bottom and left):
        raise RuntimeError("Rahmen im Scan nicht gefunden")
    y0, y1, x0 = top[0], bottom[0], left[0]
    # rechte Kante: erste lange Senkrechte rechts davon (fällt mit der Plankopf-Trennlinie zusammen)
    lw = next(b - a_ for a_, b in rows if abs((a_ + b) / 2 - y0) < 1)
    x1 = next(a_ for a_, b in cols if a_ > x0 + 100 and a[int(y0):int(y1), a_:b].mean() > 0.9) + lw / 2
    # Ticks: senkrechte/waagerechte Striche außerhalb der äußeren dünnen Linie
    ticks = []
    band = lambda lo, hi: slice(int(lo) + 3, int(hi) - 3)
    for edge, outer, sign in (("top", top[1], -1), ("bottom", bottom[1], 1)):
        lo, hi = sorted((outer, outer + sign * BAR * k))
        prof = a[band(lo, hi), int(x0):int(x1)].mean(0) > 0.95
        for s, e in runs(prof):
            if e - s < 8:
                x = x0 + (s + e - 1) / 2
                ticks.append((edge, x, y0 if edge == "top" else y1, x, hi if sign > 0 else lo))
    lo, hi = left[1] - BAR * k, left[1]
    prof = a[int(y0):int(y1), band(lo, hi)].mean(1) > 0.95
    for s, e in runs(prof):
        if e - s < 8:
            y = y0 + (s + e - 1) / 2
            ticks.append(("left", x0, y, lo, y))
    # OCR der Randstreifen (Bildpixel)
    m = BAR * k + 3      # Tickband aussparen, sonst verschmilzt Tesseract Tick und Ziffern
    words = (ocr(img, (0, 0, int(x1), int(top[1] - m)))
             + ocr(img, (0, int(bottom[1] + m), int(x1), H))
             + ocr(img, (0, int(top[1]), int(left[1] - m), int(bottom[1]))))
    corners = corners_from(words, (x0, y0, x1, y1), parse=dms_ocr)
    for c in corners:
        c["x"], c["y"] = to_pt(c["x"], c["y"])
    pt_ticks = [(e, *to_pt(x, y), *to_pt(ox, oy)) for e, x, y, ox, oy in ticks]
    pt_words = [(*to_pt(w[0], w[1]), *to_pt(w[2], w[3]), w[4]) for w in words]
    head = " ".join(w[4] for w in words if w[1] < top[1])
    kopf = ocr_text(img, (int(x1) + 10, 0, W, H))
    kopf = kopf.replace("Mafsstab", "Maßstab").replace("Mafstab", "Maßstab")
    rot = re.search(r"Rotation\s*:\s*(\d+)", head)
    scale = re.search(r"\b1\s*:\s*(\d{3,5})\b", kopf) or re.search(r"\b1\s*:\s*(\d{3,5})\b", head)
    meta = title_block(kopf)
    meta.update(scale=int(scale[1]) if scale else 0, rotation=rot and rot[1])
    return (*to_pt(x0, y0), *to_pt(x1, y1)), pt_ticks, pt_words, corners, meta


if __name__ == "__main__":   # Selbsttest des OCR-Parsers mit real beobachteten Lesarten
    cases = {"9*58'31,1\"": (9, 58, 31.1), "542041,3\"": (54, 20, 41.3), "54*2028,5\"": (54, 20, 28.5),
             "10%0'35,4\"": (10, 0, 35.4), "9723'58,8\"": (9, 23, 58.8), "54°1'4,4\"": (54, 1, 4.4)}
    for s, (d, m, sec) in cases.items():
        assert abs(dms_ocr(s) - (d + m / 60 + sec / 3600)) < 1e-9, s
    for s in ("10720\"", "A0\"", "1,3\"", "54°0'0\"", "547234,5\""):
        assert dms_ocr(s) is None, s
    print("ok")


# --------------------------------------------------------------------------- Tiefenfarben der Scans
# Legendenfarben der gescannten Bände (wie NOK-88-91, Grenzen in m): nur für die Tiefenfläche
SCAN_LEGEND = [(0, 5, (254, 216, 177)), (5, 10, (254, 183, 148)), (10, 10.5, (170, 254, 192)),
               (10.5, 11, (220, 255, 255)), (11, 12, (176, 212, 248)), (12, 13, (169, 175, 249)),
               (13, 14, (117, 186, 255)), (14, 25, (18, 133, 247))]
VORLAGE = ("20260803-NOK-88-91.pdf", 7)   # Vektorblatt gleicher Schrift: Ziffern-Vorlagen
K0 = 2 * 170 / 72                         # Ziffernerkennung immer bei dieser Auflösung (px/pt)
DH = 28                                   # Ziffernhöhe bei K0 (px)


def _black(a):
    return (a.max(2) < 110) & (a.max(2).astype(np.int16) - a.min(2) < 60)


def _norm(m):
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((12, 16), Image.BILINEAR), np.float32).ravel() / 255


def _templates():
    """Ziffern-Vorlagen aus dem Vektorblatt: Zeichen-Bbox (rawdict) -> schwarze Komponente darunter."""
    import build
    from scipy import ndimage
    pdf, pno = Path("data/pdf") / VORLAGE[0], VORLAGE[1]
    page = pymupdf.open(pdf)[pno - 1]
    W, H = page.rect.width, page.rect.height
    sub = (W * 0.3, H * 0.15, W * 0.55, H * 0.85)
    with tempfile.TemporaryDirectory() as td:
        a = np.asarray(build.ppm(pdf, pno, sub, K0, f"{td}/t"))
    lab, _ = ndimage.label(_black(a))
    sl = ndimage.find_objects(lab)
    hits = []
    for b in page.get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            if abs(l["dir"][1]) > 0.01 or l["dir"][0] < 0:
                continue
            for s in l["spans"]:
                for ch in s["chars"] if s["color"] == 0 else []:
                    x, y = ((ch["bbox"][0] + ch["bbox"][2]) / 2 - int(sub[0] * K0) / K0) * K0, \
                           ((ch["bbox"][1] + ch["bbox"][3]) / 2 - int(sub[1] * K0) / K0) * K0
                    if ch["c"].isdigit() and 3 <= y < a.shape[0] - 4 and 3 <= x < a.shape[1] - 4:
                        ids = np.unique(lab[int(y) - 3:int(y) + 4, int(x) - 3:int(x) + 4])
                        if len(ids[ids > 0]) == 1:
                            hits.append((ch["c"], ids[ids > 0][0] - 1))
    from collections import Counter
    n = Counter(i for _, i in hits)
    C, M = [], []
    for c, i in hits:                       # nur Komponenten mit genau einer Ziffer (nicht verschmolzen)
        m = (lab[sl[i]] == i + 1)[:DH]                  # wie im Scan: Komma abschneiden
        m = m[:, np.flatnonzero(m.any(0))[0]:np.flatnonzero(m.any(0))[-1] + 1]
        if n[i] == 1 and m.shape[0] >= 20 and (0.45 < m.shape[1] / m.shape[0] < 0.95 or c == "1"):
            C.append(c); M.append(_norm(m))
    return np.array(C), np.array(M)


def soundings(a, T):
    """Tiefenkoten (x, y, m) aus dem Scanbild a (RGB bei K0): Ziffern per Vorlage, je 2–3 Ziffern = d,d."""
    from scipy import ndimage
    C, M = T
    lab, _ = ndimage.label(_black(a))
    g = []
    for i, s in enumerate(ndimage.find_objects(lab)):
        h, w = s[0].stop - s[0].start, s[1].stop - s[1].start
        if not 24 <= h <= 36 or w > 70:
            continue
        m = (lab[s] == i + 1)[:DH]                       # Komma unter der Ziffer abschneiden
        c = np.flatnonzero(m.any(0))
        m, x0 = m[:, c[0]:c[-1] + 1], s[1].start + c[0]
        w = m.shape[1]
        n = max(1, round(w / 15)) if w > 21 else 1     # verschmolzene Ziffern gleichmäßig teilen
        for j in range(n):
            p = m[:, j * w // n:(j + 1) * w // n]
            c, r = np.flatnonzero(p.any(0)), np.flatnonzero(p.any(1))
            if not len(c) or r[-1] - r[0] < 20:
                continue
            d = ((M - _norm(p[r[0]:r[-1] + 1, c[0]:c[-1] + 1])) ** 2).mean(1)
            g.append((x0 + j * w // n + c[0], s[0].start + r[0], c[-1] - c[0] + 1, r[-1] - r[0] + 1, C[d.argmin()]))
    g.sort()
    used, out = set(), []
    for a_ in range(len(g)):
        if a_ in used:
            continue
        run = [a_]
        for b in range(a_ + 1, len(g)):
            x, y, w, h, _ = g[run[-1]]
            X, Y, W, H, _ = g[b]
            if X > x + 6 * 15:
                break
            if b not in used and X - (x + w) <= 18 and X >= x + 0.5 * w and abs(Y + H / 2 - y - h / 2) < 0.35 * h:
                run.append(b)
        if 2 <= len(run) <= 3:
            used.update(run)
            xs = [g[i][0] for i in run] + [g[i][0] + g[i][2] for i in run]
            ys = [g[i][1] for i in run] + [g[i][1] + g[i][3] for i in run]
            out.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, int("".join(g[i][4] for i in run)) / 10))
    return np.array(out).reshape(-1, 3)


def classes(a, tol=14):
    """Legendenklasse je Pixel (255 = keine): Grundfarbe aufgehellt/abgedunkelt (Schummerung) wie im Original."""
    base = np.array([c for *_, c in SCAN_LEGEND], np.float32)
    out = np.full(a.shape[:2], 255, np.uint8)
    for r in range(0, a.shape[0], 256):
        p = a[r:r + 256].astype(np.float32)
        best = np.full(p.shape[:2], np.inf, np.float32)
        for i, b in enumerate(base):
            sd = np.clip((p / b).mean(2, keepdims=True), 0.6, 1)          # abdunkeln bis 40 %
            sl = np.clip(((255 - p) / np.maximum(255 - b, 8)).mean(2, keepdims=True), 0.55, 1)   # aufhellen bis 45 %
            e = np.minimum(np.abs(p - b * sd).max(2), np.abs(p - 255 + (255 - b) * sl).max(2))
            better = e < best
            best[better] = e[better]
            out[r:r + 256][better] = i
        out[r:r + 256][best > tol] = 255
    return out


def recolor(pdf, pno, frame, k, s, td):
    """Scan: Koten per Ziffern-Vorlagen (nur auf Tiefenfläche, Ausreißer gegen Nachbarn raus), Fläche aus den
    Legendenfarben. Die Farben selbst passen nicht genau zu den Koten (11,x auf 12–13 m), daher färben nur die Koten."""
    import build
    from scipy import ndimage, spatial
    a0 = np.asarray(build.ppm(pdf, pno, frame, K0, f"{td}/o"))
    cm0 = classes(a0)
    kot = soundings(a0, _templates())
    # Farbklasse unter der Zahl (häufigste im Umfeld) grob passend (±1,5 m; die Scan-Farben sind etwas versetzt)
    lo = np.array([l for l, _, _ in SCAN_LEGEND], np.float32)
    hi = np.array([h for _, h, _ in SCAN_LEGEND], np.float32)
    ok = np.zeros(len(kot), bool)
    for i, (x, y, v) in enumerate(kot):
        w = cm0[max(0, int(y) - 25):int(y) + 26, max(0, int(x) - 35):int(x) + 36]
        w = w[w < 255]
        if len(w) > 50:
            c = np.bincount(w).argmax()
            ok[i] = lo[c] - 1.5 <= v <= hi[c] + 1.5
    kot = kot[ok]
    if len(kot) > 10:     # Ausreißer: mind. 2 der 8 Nachbarn innerhalb 1,5 m (Böschung: 2 m neben 11 m ist echt)
        _, j = spatial.cKDTree(kot[:, :2]).query(kot[:, :2], 9)
        kot = kot[(np.abs(kot[j[:, 1:], 2] - kot[:, 2:3]) <= 1.5).sum(1) >= 2]
    print(f"{Path(pdf).name} S. {pno}: {len(kot)} Koten aus dem Scan", file=sys.stderr)
    if len(kot) < 10:
        return None
    a = a0 if abs(k - K0) < 1e-6 else np.asarray(build.ppm(pdf, pno, frame, k, f"{td}/p"))
    cm = cm0 if a is a0 else np.asarray(Image.fromarray(cm0).resize(a.shape[1::-1], Image.NEAREST))
    del a0, cm0
    px_m = s / k
    classes_hit = cm < 255
    sat = a.max(2).astype(np.int16) - a.min(2)
    mask = ndimage.binary_opening(classes_hit | (sat >= 20), iterations=2)   # dünne farbige Linien fallen weg
    mask = ndimage.binary_closing(mask, iterations=3)
    line = (np.abs(a.astype(np.int16) - (73, 155, 254)).max(2) < 50) | (np.abs(a.astype(np.int16) - (0, 0, 192)).max(2) < 60)
    mask &= ~ndimage.binary_dilation(line)                             # Uferlinie/Achse bleiben
    lab, _ = ndimage.label(~mask)                                         # Löcher unter Zahlen/Linien
    mask |= np.r_[False, np.bincount(lab.ravel())[1:] * px_m ** 2 < 25][lab]
    del lab
    # Linien auf Weiß: Pixel der Legendenfarben weiß, übrige in der Fläche (Zahlen, Kanten) grau
    out = a.copy()
    out[classes_hit] = 255
    rest = mask & ~classes_hit & (a.max(2) < 150)          # dunkel: Zahlen/Linien grau, sonst weiß
    out[mask & ~classes_hit & ~rest] = 255
    out[rest] = a[rest].mean(1, keepdims=True).astype(np.uint8)
    return build.paint(mask, kot[:, :2] * (k / K0), kot[:, 2], px_m, out)
