"""Provider-neutral structured extraction with an LLM.

``StructuredLLM`` is the only interface the rest of the code sees. ``OpenAIStructuredLLM``
implements it with the OpenAI Responses API and works for OpenAI and Azure OpenAI alike.
Tests use a fake implementation, so CI needs no API key (see ADR 0006).
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from belegfluss.config import Settings


class LLMNotConfiguredError(RuntimeError):
    """No model configured, but the document needs an LLM (PDF without e-invoice, scan)."""


class LLMExtractionError(RuntimeError):
    """The model returned no parseable result (refusal, truncation, schema violation)."""


@dataclass
class LLMUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0

    def add(self, other: LLMUsage) -> None:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.seconds += other.seconds


@dataclass
class LLMResult[T: BaseModel]:
    parsed: T
    usage: LLMUsage = field(default_factory=LLMUsage)


class StructuredLLM(Protocol):
    model: str

    def extract[M: BaseModel](
        self,
        schema: type[M],
        instructions: str,
        text: str | None = None,
        images: list[bytes] | None = None,
    ) -> LLMResult[M]: ...


def png_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


class OpenAIStructuredLLM:
    def __init__(self, client: Any, model: str, image_detail: str = "high") -> None:
        self.client = client
        self.model = model
        self.image_detail = image_detail

    def extract[M: BaseModel](
        self,
        schema: type[M],
        instructions: str,
        text: str | None = None,
        images: list[bytes] | None = None,
    ) -> LLMResult[M]:
        content: list[dict[str, str]] = []
        if text is not None:
            content.append({"type": "input_text", "text": text})
        for png in images or []:
            content.append(
                {"type": "input_image", "image_url": png_data_url(png), "detail": self.image_detail}
            )
        if not content:
            raise ValueError("nothing to extract from")
        started = time.perf_counter()
        response = self.client.responses.parse(
            model=self.model,
            instructions=instructions,
            input=[{"role": "user", "content": content}],
            text_format=schema,
        )
        elapsed = time.perf_counter() - started
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise LLMExtractionError(f"model returned no structured output: {response!r}"[:500])
        usage = getattr(response, "usage", None)
        return LLMResult(
            parsed=parsed,
            usage=LLMUsage(
                calls=1,
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                seconds=elapsed,
            ),
        )


def create_openai_client(settings: Settings) -> Any:
    """OpenAI or Azure OpenAI client from configuration; shared by LLM and embeddings."""
    if settings.llm_provider == "azure":
        from openai import AzureOpenAI

        if not (settings.azure_openai_endpoint and settings.azure_openai_api_version):
            raise LLMNotConfiguredError(
                "Azure needs BELEGFLUSS_AZURE_OPENAI_ENDPOINT and "
                "BELEGFLUSS_AZURE_OPENAI_API_VERSION."
            )
        azure_key = settings.azure_openai_api_key
        return AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            api_key=azure_key.get_secret_value() if azure_key else None,
        )
    from openai import OpenAI

    key = settings.openai_api_key
    if key is None:
        raise LLMNotConfiguredError("Set OPENAI_API_KEY in the environment or in .env.")
    return OpenAI(api_key=key.get_secret_value())


def create_llm(settings: Settings) -> StructuredLLM:
    """Build the configured LLM client. Raises if no model is configured."""
    if not settings.llm_model:
        raise LLMNotConfiguredError(
            "Set BELEGFLUSS_LLM_MODEL to a model that supports vision and structured outputs "
            "(on Azure: the deployment name), and provide the API key via OPENAI_API_KEY or "
            "AZURE_OPENAI_API_KEY."
        )
    client = create_openai_client(settings)
    return OpenAIStructuredLLM(client, settings.llm_model, settings.llm_image_detail)
