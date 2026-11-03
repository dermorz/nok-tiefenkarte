"""Passpunkte für Bände, deren Kartenblatt nur als Bild (JPEG) im PDF liegt: Rahmen und Ticks aus
Pixeln, Gitterlabels/Eckwerte/Plankopf per Tesseract-OCR. Gleiches Blattlayout wie die Vektorbände."""
import re, subprocess, tempfile

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
