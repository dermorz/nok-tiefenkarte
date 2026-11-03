"""Lagekontrolle über die Basiskarte: Ufer-/Weglinien sind in benachbarten Blättern dieselbe Zeichnung
(DBWK). Vergleich der z19-Quellkacheln beider Blätter außerhalb der Messflächen -> Versatz in m.

    python check_lines.py <blatt-id-a> <blatt-id-b>     (beide vorher mit tiles.py gerendert)
"""
import math, sys
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path("out/web/src")


def mosaic(sid, keys, x0, y0, nx, ny):
    img = np.zeros((ny * 256, nx * 256), np.float32)
    for X, Y in keys:
        p = np.asarray(Image.open(SRC / sid / "plan" / f"{X}_{Y}.png").convert("RGBA")).astype(np.float32)
        m = SRC / sid / "mess" / f"{X}_{Y}.png"
        mess = np.asarray(Image.open(m))[..., 3] if m.exists() else 0
        line = (p[..., 3] > 128) & (np.asarray(mess) < 10)
        img[(Y - y0) * 256:(Y - y0 + 1) * 256, (X - x0) * 256:(X - x0 + 1) * 256] = line
    return img


def main(a, b):
    ka = {tuple(map(int, f.stem.split("_"))) for f in (SRC / a / "plan").glob("*.png")}
    kb = {tuple(map(int, f.stem.split("_"))) for f in (SRC / b / "plan").glob("*.png")}
    keys = ka & kb
    if not keys:
        sys.exit("keine gemeinsamen Kacheln")
    xs, ys = [k[0] for k in keys], [k[1] for k in keys]
    x0, y0 = min(xs), min(ys)
    nx, ny = max(xs) - x0 + 1, max(ys) - y0 + 1
    A, B = mosaic(a, keys, x0, y0, nx, ny), mosaic(b, keys, x0, y0, nx, ny)
    F = np.fft.rfft2(A - A.mean()) * np.conj(np.fft.rfft2(B - B.mean()))
    cc = np.fft.irfft2(F / (np.abs(F) + 1e-6), A.shape)
    iy, ix = np.unravel_index(cc.argmax(), cc.shape)
    # Subpixel per Parabel
    def sub(c_m, c0, c_p):
        d = c_m - 2 * c0 + c_p
        return 0.5 * (c_m - c_p) / d if d else 0.0
    sy = sub(cc[iy - 1, ix], cc[iy, ix], cc[(iy + 1) % cc.shape[0], ix])
    sx = sub(cc[iy, ix - 1], cc[iy, ix], cc[iy, (ix + 1) % cc.shape[1]])
    dy = (iy if iy < cc.shape[0] // 2 else iy - cc.shape[0]) + sy
    dx = (ix if ix < cc.shape[1] // 2 else ix - cc.shape[1]) + sx
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y0 + ny / 2) / 2**19))))
    px = 156543.034 / 2**19 * math.cos(math.radians(lat))
    print(f"{a} vs {b}: {len(keys)} Kacheln, Linienpixel {int(A.sum())}/{int(B.sum())}, "
          f"Versatz dE={dx * px:+.2f} m dN={-dy * px:+.2f} m, Peak {cc.max() / cc.std():.0f}σ")


if __name__ == "__main__":
    main(*sys.argv[1:3])
