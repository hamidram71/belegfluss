"""``belegfluss-eval extraction|checks`` – writes a Markdown report to reports/."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from belegfluss import __version__
from belegfluss.config import get_settings
from belegfluss.domain.documents import DocumentKind
from belegfluss.evaluation import agent_eval, checks_eval, extraction_eval, injection_eval
from belegfluss.extraction.llm import StructuredLLM, create_llm
from belegfluss.extraction.pipeline import extract_delivery_note, extract_invoice
from belegfluss.master_data import MasterData
from belegfluss.runtime import create_match_graph

LLM_FORMATS = {"pdf", "scan_png"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Belegfluss against ground truth.")
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extraction", help="field accuracy of document extraction")
    ex.add_argument("--data", type=Path, default=Path("data/synthetic"))
    ex.add_argument("--limit", type=int, default=20, help="max sets (LLM calls cost money)")
    ex.add_argument("--kinds", default="invoice,delivery_note")
    ex.add_argument(
        "--formats", default=None, help="comma list, e.g. pdf,scan_png; default: all formats"
    )
    ex.add_argument("--no-llm", action="store_true", help="only XML / ZUGFeRD, no API calls")
    ex.add_argument("--cache", type=Path, default=Path("reports/cache"))
    ck = sub.add_parser("checks", help="precision / recall of the rule-based checks")
    ck.add_argument("--data", type=Path, default=Path("data/synthetic"))
    ck.add_argument("--source", choices=["ground-truth", "extracted"], default="ground-truth")
    ck.add_argument("--cache", type=Path, default=Path("reports/cache"))
    ck.add_argument("--limit", type=int, default=None)
    ag = sub.add_parser("agent", help="category and clause accuracy of the matching agent")
    ag.add_argument("--data", type=Path, default=Path("data/synthetic"))
    ag.add_argument("--source", choices=["ground-truth", "extracted"], default="ground-truth")
    ag.add_argument("--adjudicator", choices=["deterministic", "llm"], default="deterministic")
    ag.add_argument(
        "--embedder",
        choices=["hashing", "openai"],
        default="hashing",
        help="hashing = offline lexical baseline; openai = BELEGFLUSS_EMBEDDING_MODEL",
    )
    ag.add_argument("--cache", type=Path, default=Path("reports/cache"))
    ag.add_argument("--limit", type=int, default=None)
    inj = sub.add_parser("injection", help="prompt-injection defences on an adversarial dataset")
    inj.add_argument("--data", type=Path, default=Path("data/adversarial"))
    inj.add_argument("--no-llm", action="store_true", help="screening only, no API calls")
    inj.add_argument("--cache", type=Path, default=Path("reports/cache-adversarial"))
    inj.add_argument("--limit", type=int, default=None, help="max attacks to evaluate")
    args = parser.parse_args(argv)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    reports = Path("reports")
    reports.mkdir(exist_ok=True)

    if args.command == "extraction":
        master = MasterData.load(args.data / "master_data")
        llm: StructuredLLM | None = None if args.no_llm else create_llm(get_settings())
        formats = set(args.formats.split(",")) if args.formats else None
        if args.no_llm:
            formats = (formats or {"xrechnung_cii", "zugferd_pdf"}) - LLM_FORMATS
        kinds = tuple(DocumentKind(k) for k in args.kinds.split(","))

        def extract(kind: DocumentKind, data: bytes):  # type: ignore[no-untyped-def]
            if kind is DocumentKind.INVOICE:
                return extract_invoice(data, master, llm)
            return extract_delivery_note(data, master, llm)

        results = extraction_eval.run_extraction_eval(
            args.data, kinds, extract, args.limit, formats, args.cache
        )
        body = extraction_eval.to_markdown(results)
        title = f"# Extraction evaluation {stamp}\n\nModel: {llm.model if llm else 'none'}\n\n"
    elif args.command == "checks":
        report = checks_eval.run_checks_eval(args.data, args.source, args.cache, args.limit)
        body = checks_eval.to_markdown(report)
        title = f"# Checks evaluation {stamp} (input: {args.source})\n\n"
    elif args.command == "injection":
        master = MasterData.load(args.data / "master_data")
        llm = None if args.no_llm else create_llm(get_settings())

        def extract_attacked(kind: DocumentKind, data: bytes):  # type: ignore[no-untyped-def]
            if kind is DocumentKind.INVOICE:
                return extract_invoice(data, master, llm)
            return extract_delivery_note(data, master, llm)

        injection_report = injection_eval.run_injection_eval(
            args.data, None if args.no_llm else extract_attacked, args.cache, args.limit
        )
        body = injection_eval.to_markdown(injection_report)
        title = (
            f"# Prompt-injection evaluation {stamp}\n\n"
            f"Model: {llm.model if llm else 'none (screening only)'}\n\n"
        )
    else:
        settings = get_settings().model_copy(
            update={
                "database_url": None,  # evaluate on a fresh in-memory index of this dataset
                "contracts_dir": args.data / "contracts",
                "adjudicator": args.adjudicator,
                "embedding_model": (get_settings().embedding_model or "text-embedding-3-small")
                if args.embedder == "openai"
                else None,
            }
        )
        master = MasterData.load(args.data / "master_data")
        llm = create_llm(settings) if args.adjudicator == "llm" else None
        graph, retriever = create_match_graph(settings, master, llm)
        agent_report = agent_eval.run_agent_eval(
            args.data, graph, args.source, args.cache, args.limit
        )
        body = agent_eval.to_markdown(agent_report)
        title = (
            f"# Agent evaluation {stamp} (input: {args.source})\n\n"
            f"Adjudicator: {args.adjudicator}{f' ({llm.model})' if llm else ''}; "
            f"embedder: {retriever.embedder.name}; generator {__version__}\n\n"
        )

    path = reports / f"{args.command}-{stamp}.md"
    path.write_text(title + body + "\n", encoding="utf-8")
    print(title + body)
    print(f"\nReport written to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
