"""Turning text into vectors, behind a port, with the vendor SDK and an offline stand-in."""

import hashlib
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Protocol

import openai
from openai import AsyncOpenAI

from frontdesk.providers.port import (
    ModelRejectedError,
    ModelThrottledError,
    ModelTimeoutError,
    ModelUnavailableError,
    Usage,
)

DIMENSIONS = 1536
"""The width of the stored vectors, which is the width of text-embedding-3-small."""


@dataclass(frozen=True)
class Embedded:
    vectors: list[list[float]]
    usage: Usage
    latency_ms: int


class Embedder(Protocol):
    name: str
    model: str
    max_distance: float
    """The cosine distance past which a chunk is not about the question. It belongs to the
    embedder because each model spreads its vectors differently."""

    async def embed(self, texts: list[str]) -> Embedded: ...


class AzureOpenAIEmbedder:
    """An embedding deployment on Azure OpenAI.

    The default threshold was chosen on the labelled questions for text-embedding-3-small
    (docs/medicoes.md): the lowest that still finds every answer. It does not keep
    retrieval quiet for questions the knowledge base has no answer to.
    """

    name = "azure_openai"

    def __init__(
        self, client: AsyncOpenAI, model: str, *, max_distance: float = 0.65, timeout_s: float = 15
    ) -> None:
        self._client = client
        self.model = model
        self.max_distance = max_distance
        self._timeout_s = timeout_s

    async def embed(self, texts: list[str]) -> Embedded:
        started = time.perf_counter()
        try:
            done = await self._client.embeddings.create(
                model=self.model, input=texts, timeout=self._timeout_s
            )
        except openai.APITimeoutError as error:
            raise ModelTimeoutError(str(error)) from error
        except openai.RateLimitError as error:
            raise ModelThrottledError(str(error)) from error
        except (openai.APIConnectionError, openai.InternalServerError) as error:
            raise ModelUnavailableError(str(error)) from error
        except openai.APIStatusError as error:
            raise ModelRejectedError(str(error)) from error
        return Embedded(
            vectors=[item.embedding for item in sorted(done.data, key=lambda item: item.index)],
            usage=Usage(input_tokens=done.usage.prompt_tokens, output_tokens=0),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )


class HashingEmbedder:
    """A deterministic stand-in: each word lands on a few fixed positions of the vector.

    Texts that share words end up close, which is enough to run the pipeline and its tests
    with no account. It knows nothing about meaning: "carro" and "estacionamento" are as
    far apart as any two words.
    """

    name = "offline"
    model = "offline-hashing"
    # One word in common between a short question and a short text is already a match.
    max_distance = 0.9

    async def embed(self, texts: list[str]) -> Embedded:
        return Embedded(
            vectors=[_hashed(text) for text in texts],
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=0,
        )


_WORD = re.compile(r"[a-z0-9]+")
# Words too common in pt-BR to say what a text is about.
_STOPWORDS = frozenset(
    [
        "a",
        "o",
        "as",
        "os",
        "um",
        "uma",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "para",
        "por",
        "com",
        "que",
        "se",
        "ou",
        "tem",
        "ter",
        "voces",
        "vocês",
        "eu",
        "meu",
        "minha",
        "la",
        "aqui",
        "ai",
        "e",
        "é",
        "ao",
        "aos",
    ]
)


def _hashed(text: str) -> list[float]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    vector = [0.0] * DIMENSIONS
    for word in _WORD.findall(plain):
        if word in _STOPWORDS:
            continue
        # A crude stem, so that "quadra" and "quadras" meet.
        stem = word[:-1] if len(word) > 4 and word.endswith("s") else word
        digest = hashlib.sha256(stem.encode()).digest()
        for offset in (0, 4, 8):
            position = int.from_bytes(digest[offset : offset + 4], "big") % DIMENSIONS
            vector[position] += 1.0
    length = math.sqrt(sum(value * value for value in vector))
    return [value / length for value in vector] if length else vector
