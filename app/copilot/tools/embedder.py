"""Text → 1024-dimension vectors with BAAI/bge-m3 (sentence-transformers), normalised for cosine.

The model loads once per process, from the local Hugging Face cache, on the first call. It needs
the `cpu` or `gpu` extra (torch + sentence-transformers); tests pass a fake embedder instead.
"""

import asyncio
import threading
from collections import OrderedDict

from ..config.settings import LLM

DIM = 1024


class Embedder:
    def __init__(self, model_name: str | None = None, cache_size: int | None = None):
        cfg = LLM.get("embedding", {})
        self.model_name = model_name or cfg.get("model", "BAAI/bge-m3")
        self.cache_size = cache_size or cfg.get("cache_size", 2048)
        self._model = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    def _load(self):
        with self._lock:
            if self._model is None:
                import torch
                from sentence_transformers import SentenceTransformer

                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._model = SentenceTransformer(self.model_name, device=device)
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vectors]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._encode, texts)

    async def embed_query(self, text: str) -> list[float]:
        """One question; cached (LRU) because follow-ups and retries repeat it."""
        key = " ".join(text.lower().split())
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        vector = (await self.embed([text]))[0]
        self._cache[key] = vector
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return vector


_default: Embedder | None = None


def default_embedder() -> Embedder:
    global _default
    if _default is None:
        _default = Embedder()
    return _default
