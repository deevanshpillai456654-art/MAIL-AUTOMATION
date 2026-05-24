"""
Lightweight offline embedding and semantic search module.

This module intentionally avoids heavyweight model packages and network model
downloads. It uses deterministic hashing embeddings with the same 384-dimension
shape expected by the local semantic search layer, and it can be swapped with an
ONNX MiniLM/BGE/E5 encoder later without changing callers.
"""

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import List, Tuple

import numpy as np

_log = logging.getLogger(__name__)


class EmbeddingModel:
    DIMENSION = 384

    def __init__(self, model_name: str = "all-MiniLM-local-hash"):
        self.model_name = model_name
        self._loaded = False
        self._fallback = True

    def initialize(self):
        self._loaded = True

    def encode(self, text: str) -> np.ndarray:
        self.initialize()
        return self._simple_embedding(text)

    def _simple_embedding(self, text: str) -> np.ndarray:
        tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
        embedding = np.zeros(self.DIMENSION, dtype=np.float32)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.DIMENSION
            embedding[idx] += 1.0 + (len(token) % 5) / 10.0
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def encode_batch(self, texts: List[str]) -> np.ndarray:
        self.initialize()
        return np.array([self._simple_embedding(t) for t in texts])


class VectorStore:
    def __init__(self, storage_path: str = None):
        if storage_path is None:
            base_path = Path(__file__).parent.parent / "data"
            base_path.mkdir(parents=True, exist_ok=True)
            storage_path = str(base_path / "embeddings.pkl")

        self.storage_path = storage_path
        self.vectors = []
        self.metadata = []
        self._load()

    def _load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "rb") as f:
                    data = json.load(f)
                    self.vectors = data.get("vectors", [])
                    self.metadata = data.get("metadata", [])
            except Exception as exc:
                self.vectors = []
                self.metadata = []
                _log.warning("Could not load embeddings store %s: %s", self.storage_path, exc)

    def _save(self):
        with open(self.storage_path, "wb") as f:
            json.dump({"vectors": self.vectors, "metadata": self.metadata}, f)

    def add(self, vector: np.ndarray, metadata: dict):
        self.vectors.append(vector)
        self.metadata.append(metadata)
        self._save()

    def add_batch(self, vectors: np.ndarray, metadata_list: List[dict]):
        self.vectors.extend(vectors)
        self.metadata.extend(metadata_list)
        self._save()

    def search(self, query_vector: np.ndarray, top_k: int = 10) -> List[Tuple[float, dict]]:
        if not self.vectors:
            return []

        vectors_array = np.array(self.vectors)
        query_vector = query_vector.reshape(1, -1)
        similarities = np.dot(vectors_array, query_vector.T).flatten()
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if similarities[idx] > 0.1:
                results.append((float(similarities[idx]), self.metadata[idx]))
        return results

    def delete_by_email_id(self, email_id: int):
        keep_vectors = []
        keep_meta = []
        for vector, meta in zip(self.vectors, self.metadata):
            if meta.get("email_id") != email_id:
                keep_vectors.append(vector)
                keep_meta.append(meta)
        self.vectors = keep_vectors
        self.metadata = keep_meta
        self._save()

    def clear(self):
        self.vectors = []
        self.metadata = []
        self._save()

    def count(self) -> int:
        return len(self.vectors)


class SemanticSearch:
    def __init__(self):
        self.embedding_model = EmbeddingModel()
        self.vector_store = VectorStore()

    def index_email(self, email_id: int, subject: str, sender: str, body: str):
        text = f"{subject} {sender} {body[:500]}"
        vector = self.embedding_model.encode(text)
        self.vector_store.add(vector, {"email_id": email_id, "subject": subject, "sender": sender})

    def search(self, query: str, top_k: int = 10) -> List[dict]:
        query_vector = self.embedding_model.encode(query)
        results = self.vector_store.search(query_vector, top_k)
        return [
            {"score": score, "email_id": meta["email_id"], "subject": meta["subject"], "sender": meta["sender"]}
            for score, meta in results
        ]

    def reindex_all(self, emails: List[dict]):
        self.vector_store.clear()
        texts = []
        metadata = []
        for email in emails:
            text = f"{email.get('subject', '')} {email.get('sender', '')} {email.get('body', '')[:500]}"
            texts.append(text)
            metadata.append({"email_id": email.get("id"), "subject": email.get("subject"), "sender": email.get("sender")})
        vectors = self.embedding_model.encode_batch(texts)
        self.vector_store.add_batch(vectors, metadata)
