from __future__ import annotations

import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from belegfluss.config import Settings
from belegfluss.extraction.llm import (
    LLMExtractionError,
    LLMNotConfiguredError,
    OpenAIStructuredLLM,
    create_llm,
)
from belegfluss.extraction.llm_extract import ExtractionError, to_delivery_note, to_invoice
from belegfluss.extraction.pipeline import ExtractionMethod, extract_delivery_note, extract_invoice
from belegfluss.extraction.schemas import ExtractedInvoice
from belegfluss.master_data import MasterData
from belegfluss.synth.render_pdf import render_delivery_note_pdf, render_invoice_pdf
from belegfluss.synth.render_xml import render_invoice_xml
from belegfluss.synth.scan import pdf_to_scan_png
from belegfluss.synth.scenarios import generate_set
from belegfluss.synth.world import World

from .fakes import FakeLLM, transcribe_delivery_note, transcribe_invoice


@pytest.mark.parametrize("german", [False, True])
def test_perfect_transcription_maps_to_the_exact_invoice(
    world: World, master: MasterData, german: bool
) -> None:
    rng = random.Random(31)
    for index in range(1, 40):
        invoice = generate_set(rng, world, index).invoice
        assert to_invoice(transcribe_invoice(invoice, german), master) == invoice


def test_invalid_transcription_lists_every_problem(world: World, master: MasterData) -> None:
    invoice = generate_set(random.Random(32), world, 1).invoice
    broken = transcribe_invoice(invoice)
    lines = [
        broken.lines[0].model_copy(update={"unit": "Fass"}),
        broken.lines[0].model_copy(update={"unit_price": None}),
    ]
    with pytest.raises(ExtractionError) as error:
        to_invoice(broken.model_copy(update={"lines": lines}), master)
    assert "line 1" in str(error.value) and "line 2" in str(error.value)


def test_digital_pdf_is_sent_as_text(world: World, master: MasterData) -> None:
    invoice = generate_set(random.Random(33), world, 1).invoice
    llm = FakeLLM([transcribe_invoice(invoice)])
    result = extract_invoice(render_invoice_pdf(invoice), master, llm)
    call = llm.calls[0]
    assert result.method is ExtractionMethod.LLM_TEXT
    assert call["images"] is None and invoice.invoice_number in call["text"]
    assert call["text"].startswith("<document>") and "untrusted" in call["instructions"]
    assert result.document == invoice
    assert result.usage.calls == 1


def test_scan_is_sent_as_image(world: World, master: MasterData) -> None:
    generated = generate_set(random.Random(34), world, 1)
    scan = pdf_to_scan_png(render_delivery_note_pdf(generated.delivery_note), random.Random(1))
    llm = FakeLLM([transcribe_delivery_note(generated.delivery_note)])
    result = extract_delivery_note(scan, master, llm)
    assert result.method is ExtractionMethod.LLM_VISION
    assert llm.calls[0]["text"] is None and llm.calls[0]["images"] == [scan]
    assert result.document == generated.delivery_note


def test_e_invoices_never_call_the_llm(world: World, master: MasterData) -> None:
    invoice = generate_set(random.Random(35), world, 1).invoice
    llm = FakeLLM([])
    assert (
        extract_invoice(render_invoice_xml(invoice), master, llm).method is ExtractionMethod.CII_XML
    )
    assert llm.calls == []


def test_pdf_without_llm_raises_clear_error(world: World, master: MasterData) -> None:
    invoice = generate_set(random.Random(36), world, 1).invoice
    with pytest.raises(LLMNotConfiguredError):
        extract_invoice(render_invoice_pdf(invoice), master, None)


class _StubResponses:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def test_openai_adapter_builds_responses_request(world: World) -> None:
    parsed = transcribe_invoice(generate_set(random.Random(37), world, 1).invoice)
    responses = _StubResponses(
        SimpleNamespace(
            output_parsed=parsed, usage=SimpleNamespace(input_tokens=900, output_tokens=200)
        )
    )
    llm = OpenAIStructuredLLM(SimpleNamespace(responses=responses), "some-model", "high")
    result = llm.extract(ExtractedInvoice, "instr", text="hello", images=[b"\x89PNG"])
    sent = responses.kwargs
    assert sent["model"] == "some-model" and sent["text_format"] is ExtractedInvoice
    content = sent["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "hello"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert (result.usage.input_tokens, result.usage.output_tokens) == (900, 200)


def test_openai_adapter_raises_when_nothing_parsed() -> None:
    responses = _StubResponses(SimpleNamespace(output_parsed=None, usage=None))
    llm = OpenAIStructuredLLM(SimpleNamespace(responses=responses), "m")
    with pytest.raises(LLMExtractionError):
        llm.extract(ExtractedInvoice, "instr", text="x")


def test_create_llm_requires_a_model() -> None:
    with pytest.raises(LLMNotConfiguredError):
        create_llm(Settings(llm_model=None))
    with pytest.raises(LLMNotConfiguredError):
        create_llm(Settings(llm_model="dep", llm_provider="azure"))


def test_api_key_is_read_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "BELEGFLUSS_LLM_MODEL=some-model\nOPENAI_API_KEY=sk-test-123\n", encoding="utf-8"
    )
    settings = Settings(_env_file=env)  # type: ignore[call-arg]
    assert settings.llm_model == "some-model"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-test-123"
    assert "sk-test-123" not in repr(settings)  # secrets never end up in logs
    llm = create_llm(settings)
    assert isinstance(llm, OpenAIStructuredLLM) and llm.model == "some-model"


def test_missing_key_gives_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMNotConfiguredError, match="OPENAI_API_KEY"):
        create_llm(Settings(_env_file=None, llm_model="m"))  # type: ignore[call-arg]


def test_missing_unit_falls_back_to_master_data_with_a_warning(
    world: World, master: MasterData
) -> None:
    note = generate_set(random.Random(5), world, 1).delivery_note
    transcription = transcribe_delivery_note(note)
    lines = list(transcription.lines)
    lines[0] = lines[0].model_copy(update={"unit": None})
    warnings: list[str] = []
    result = to_delivery_note(transcription.model_copy(update={"lines": lines}), master, warnings)
    assert result.items[0].unit == note.items[0].unit
    assert len(warnings) == 1 and "unit missing" in warnings[0]


def test_missing_unit_of_unknown_article_is_still_an_error(
    world: World, master: MasterData
) -> None:
    note = generate_set(random.Random(5), world, 1).delivery_note
    transcription = transcribe_delivery_note(note)
    lines = list(transcription.lines)
    lines[0] = lines[0].model_copy(update={"unit": None, "sku": "UNKNOWN-1"})
    with pytest.raises(ExtractionError, match="missing unit"):
        to_delivery_note(transcription.model_copy(update={"lines": lines}), master)
