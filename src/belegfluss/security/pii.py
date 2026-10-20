"""Mask personal and payment data before text leaves the system for a reasoning step.

Extraction necessarily sends the document itself to the model. Later steps (the agent's
judgement, logs, traces) only need facts, so identifiers are masked there: an IBAN keeps its
country code and last four digits, which is enough to tell two accounts apart.
"""

from __future__ import annotations

import re

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<!\w)(?:\+49|0)[\d /()-]{7,}\d")


def mask_iban(iban: str) -> str:
    compact = iban.replace(" ", "")
    return f"{compact[:2]}** **** {compact[-4:]}" if len(compact) > 8 else "****"


def mask_text(text: str) -> str:
    text = _IBAN.sub(lambda m: mask_iban(m.group(0)), text)
    text = _EMAIL.sub("[email]", text)
    return _PHONE.sub("[phone]", text)
