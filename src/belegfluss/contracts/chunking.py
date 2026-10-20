"""Split a contract PDF into retrievable chunks: one per clause, one per price-list row.

Clause-level chunks keep each legal statement whole and give every chunk a citable id
("§ 4", "Anlage 1"), which the agent must quote. Price-list rows become separate chunks so
that a lookup for one article returns exactly its agreed price.
"""

from __future__ import annotations

import re

import pymupdf

from belegfluss.domain.models import Model

_CONTRACT_NUMBER = re.compile(r"Vertragsnummer\s+(\S+)")
# A clause heading is a short line "§ <n> <Title>" (titles start with a capital letter).
_CLAUSE_HEADING = re.compile(r"^§ (\d+) ([A-ZÄÖÜ][^.]{1,60})$")
_ANNEX_HEADING = re.compile(r"^Anlage (\d+) – (.+)$")
_PRICE = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2,4} €$")
_TABLE_HEADER = ("Art.-Nr.", "Bezeichnung", "Einheit", "Preis netto")


class ContractParseError(ValueError):
    """The PDF does not look like a framework contract."""


class Chunk(Model):
    chunk_id: str
    contract_number: str
    clause_id: str
    title: str
    text: str


def _pdf_lines(pdf: bytes) -> list[str]:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        text = "\n".join(page.get_text() for page in doc)
    return [line.strip() for line in text.splitlines() if line.strip()]


def _price_rows(lines: list[str]) -> list[tuple[str, str, str, str]]:
    """Rows (sku, description, unit, price). A row ends at its price, so wrapped
    descriptions spanning several lines are handled."""
    rows: list[tuple[str, str, str, str]] = []
    current: list[str] = []
    for line in lines:
        if line in _TABLE_HEADER:
            continue
        current.append(line)
        if _PRICE.match(line):
            if len(current) >= 4:
                sku, *description, unit, price = current
                rows.append((sku, " ".join(description), unit, price))
            current = []
    return rows


def chunk_contract(pdf: bytes) -> list[Chunk]:
    lines = _pdf_lines(pdf)
    head = "\n".join(lines[:5])
    match = _CONTRACT_NUMBER.search(head)
    if match is None:
        raise ContractParseError("no 'Vertragsnummer' found on the first lines")
    number = match.group(1)

    sections: list[tuple[str, str, list[str]]] = []  # (clause_id, title, body lines)
    for line in lines:
        clause = _CLAUSE_HEADING.match(line)
        annex = _ANNEX_HEADING.match(line)
        if clause:
            sections.append((f"§ {clause.group(1)}", clause.group(2), []))
        elif annex:
            sections.append((f"Anlage {annex.group(1)}", annex.group(2), []))
        elif sections:
            sections[-1][2].append(line)
    if not sections:
        raise ContractParseError(f"{number}: no clauses found")

    chunks: list[Chunk] = []
    for clause_id, title, body in sections:
        if clause_id.startswith("Anlage"):
            for sku, description, unit, price in _price_rows(body):
                chunks.append(
                    Chunk(
                        chunk_id=f"{number}#{clause_id}#{sku}",
                        contract_number=number,
                        clause_id=clause_id,
                        title=title,
                        text=f"{clause_id} {title}: Artikel {sku} – {description}: "
                        f"vereinbarter Nettopreis {price} je {unit}.",
                    )
                )
            continue
        # The signature block follows the last clause; it is not part of any clause.
        text_lines = [line for line in body if not line.startswith("_")]
        cut = next(
            (i for i, line in enumerate(text_lines) if line.startswith("Heilbronn, den")),
            len(text_lines),
        )
        chunks.append(
            Chunk(
                chunk_id=f"{number}#{clause_id}",
                contract_number=number,
                clause_id=clause_id,
                title=title,
                text=f"{clause_id} {title}: " + " ".join(text_lines[:cut]),
            )
        )
    return chunks
