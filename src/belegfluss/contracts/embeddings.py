"""Text embeddings behind a small interface.

``OpenAIEmbedder`` is used for real retrieval. ``HashingEmbedder`` is an offline, deterministic
bag-of-words embedder: it needs no API key, so tests and CI can exercise the full retrieval
path. It is a lexical baseline, not a semantic model, and evaluation reports say which one
produced the numbers.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

_TOKEN = re.compile(r"[a-zäöüß0-9]+(?:-[a-z0-9]+)*", re.IGNORECASE)


class Embedder(Protocol):
    name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class HashingEmbedder:
    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions
        self.name = f"hashing-{dimensions}"

    def _features(self, text: str) -> list[str]:
        tokens = [t.lower() for t in _TOKEN.findall(text)]
        # Word tokens plus 4-character prefixes, so "Zahlungsbedingungen" and "Zahlung" meet.
        return tokens + [t[:4] for t in tokens if len(t) > 4]

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for feature in self._features(text):
                digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
            vectors.append(_normalise(vector))
        return vectors


class OpenAIEmbedder:
    def __init__(
        self, client: Any, model: str = "text-embedding-3-small", dimensions: int = 512
    ) -> None:
        self.client = client
        self.model = model
        self.dimensions = dimensions
        self.name = f"{model}-{dimensions}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 128):
            response = self.client.embeddings.create(
                model=self.model, input=texts[start : start + 128], dimensions=self.dimensions
            )
            vectors.extend(list(item.embedding) for item in response.data)
        return vectors
