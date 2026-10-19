"""Turn a digital PDF page into a realistic 'scanned paper' image.

Paper documents (especially delivery notes signed at the goods receipt) usually arrive as
scans. The artefacts below (grey paper, slight skew, noise, blur) make OCR non-trivial.
"""

from __future__ import annotations

import random
from io import BytesIO

import pymupdf
from PIL import Image, ImageChops, ImageFilter


def pdf_to_scan_png(pdf_bytes: bytes, rng: random.Random, dpi: int = 130) -> bytes:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        pix = doc[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        page = Image.frombytes("L", (pix.width, pix.height), pix.samples)

    # Slightly grey, uneven paper.
    paper = Image.new("L", page.size, color=rng.randint(225, 242))
    page = ImageChops.darker(page, paper)

    # Skew as if fed crookedly into the scanner.
    page = page.rotate(
        rng.uniform(-1.6, 1.6),
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor=rng.randint(200, 230),
    )

    # Sensor noise and a touch of blur.
    noise = Image.effect_noise(page.size, rng.uniform(8, 18))
    page = Image.blend(page, noise, alpha=rng.uniform(0.06, 0.12))
    page = page.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 0.8)))

    out = BytesIO()
    page.save(out, format="PNG", optimize=True)
    return out.getvalue()
