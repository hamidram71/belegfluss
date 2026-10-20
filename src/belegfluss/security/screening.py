"""Screen PDFs for prompt-injection attempts before any model reads them.

Two signals, both cheap and deterministic:

* hidden text: text a person cannot see (white or near-white, or smaller than 3 pt) but a
  model reading the text layer would;
* instruction-like text: phrases addressed to an AI system or overriding instructions.

A hit does not block processing; it adds an issue, which sends the match to human review.
Screening is one layer, not a guarantee: a paraphrased attack in visible text can pass it,
which is why the architecture also limits what the model can do (ADR 0009).
"""

from __future__ import annotations

import re

import pymupdf

from belegfluss.domain.models import Model

_INSTRUCTION = re.compile(
    r"ignore (all )?(previous|prior|above)|ignoriere|vorherigen anweisungen|"
    r"\bsystem\s*:|anweisung an|instruction|ki-system|ai (system|assistant|model)|"
    r"prüfsystem|sprachmodell|language model|prompt|"
    r"melde keine abweichung|report the iban|gib als .{0,40} aus",
    re.IGNORECASE,
)
MIN_VISIBLE_SIZE = 3.0
NEAR_WHITE = 0xF0


class ScreeningFlag(Model):
    code: str
    detail: str


def _is_near_white(color: int) -> bool:
    r, g, b = (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF
    return min(r, g, b) >= NEAR_WHITE


def screen_pdf(pdf: bytes) -> list[ScreeningFlag]:
    flags: list[ScreeningFlag] = []
    hidden: list[str] = []
    texts: list[str] = []
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        for page in doc:
            # White text is legitimate on a dark filled area (e.g. a table header), so light
            # text only counts as hidden if it is not drawn on such a background.
            dark_areas = [
                d["rect"]
                for d in page.get_drawings()
                if d.get("fill") is not None and min(d["fill"]) < NEAR_WHITE / 255
            ]
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text:
                            continue
                        texts.append(text)
                        x0, y0, x1, y1 = span["bbox"]
                        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                        on_dark = any(a.x0 <= cx <= a.x1 and a.y0 <= cy <= a.y1 for a in dark_areas)
                        light = _is_near_white(span["color"]) and not on_dark
                        if span["size"] < MIN_VISIBLE_SIZE or light:
                            hidden.append(text)
    hidden_text = " ".join(hidden)
    if len(hidden_text.split()) >= 3:
        flags.append(ScreeningFlag(code="hidden_text", detail=hidden_text[:160]))
    match = _INSTRUCTION.search(" ".join(texts))
    if match:
        flags.append(ScreeningFlag(code="instruction_like_text", detail=match.group(0)))
    return flags
