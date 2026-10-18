"""Section-aware chunking and a versioned, pickle-free FAISS index."""
import hashlib
import json
import re
import tempfile
from pathlib import Path

import faiss
import numpy as np
import tiktoken

from .config import Config, aws_client


def digest(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    def encode_extra(item):
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(f"Cannot serialize {type(item).__name__}")
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=encode_extra), encoding="utf-8")


def corpus_signature(config):
    files = sorted(config.policy_dir.glob("*.md"))
    if not files:
        raise ValueError(f"No policy documents in {config.policy_dir}")
    return {
        "format_version": 2,
        "sources": {p.name: digest(p.read_bytes()) for p in files},
        "embedding_model": config.embedding_model,
        "dimensions": config.dimensions,
        "chunk_tokens": config.chunk_tokens,
        "overlap_tokens": config.overlap_tokens,
        "tokenizer": "cl100k_base",
    }


def chunk_document(path, size, overlap):
    """Repeat table column headers when splitting long Markdown sections."""
    enc = tiktoken.get_encoding("cl100k_base")
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r"(?m)^# (.+)$", text)
    title = title_match.group(1) if title_match else path.stem
    doc_match = re.search(r"\*\*Document ID:\*\*\s*(\S+)", text)
    date_match = re.search(r"\*\*Effective:\*\*\s*(\S+)", text)
    doc_id = doc_match.group(1) if doc_match else path.stem
    sections = re.split(r"(?m)^(?=#{1,3} )", text)
    parent = ""
    for section in sections:
        if not section.strip():
            continue
        heading = section.splitlines()[0].strip()
        if heading.startswith("## "):
            parent = heading
        table_headers = re.findall(r"(?m)^\|[^\n]+\|\n\|[ :|\-]+\|", section)
        prefix = f"{title}\n{doc_id} | {parent} | {heading}\n"
        if table_headers:
            prefix += "\n".join(table_headers) + "\n"
        tokens = enc.encode(section)
        budget = size - len(enc.encode(prefix))
        if budget <= overlap:
            raise ValueError("Chunk size too small for section/table headers")
        for start in range(0, len(tokens), budget - overlap):
            body = enc.decode(tokens[start:start + budget])
            chunk_text = prefix + body
            yield {
                "id": digest((path.name + chunk_text).encode())[:20],
                "text": chunk_text, "doc_id": doc_id,
                "section": heading, "source": path.name,
                "effective": date_match.group(1) if date_match else None,
            }
            if start + budget >= len(tokens):
                break


class Embedder:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or aws_client("bedrock-runtime", config.region)
        self.cache = {}
        self.input_tokens = 0

    def embed(self, text):
        if text not in self.cache:
            response = self.client.invoke_model(
                modelId=self.config.embedding_model,
                contentType="application/json", accept="application/json",
                body=json.dumps({"inputText": text, "dimensions": self.config.dimensions, "normalize": True}),
            )
            payload = json.loads(response["body"].read())
            vector = np.asarray(payload["embedding"], dtype="float32")
            if vector.shape != (self.config.dimensions,) or not np.isfinite(vector).all():
                raise ValueError("Invalid embedding dimensions or values")
            self.input_tokens += payload.get("inputTextTokenCount", 0)
            self.cache[text] = vector
        return self.cache[text]


class PolicyIndex:
    def __init__(self, config: Config, embedder=None):
        self.config = config
        self.signature = corpus_signature(config)
        self.index_id = digest(json.dumps(self.signature, sort_keys=True).encode())[:20]
        self.path = config.index_root / self.index_id
        self.embedder = embedder or Embedder(config)
        self.index = None
        self.chunks = []

    def load(self):
        manifest = json.loads((self.path / "manifest.json").read_text(encoding="utf-8"))
        if manifest["signature"] != self.signature:
            raise ValueError("Index settings differ from current corpus/configuration; rebuild")
        for filename in ("index.faiss", "chunks.jsonl"):
            if digest((self.path / filename).read_bytes()) != manifest["hashes"][filename]:
                raise ValueError(f"Index integrity check failed: {filename}")
        self.index = faiss.read_index(str(self.path / "index.faiss"))
        self.chunks = [json.loads(line) for line in (self.path / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        if self.index.d != self.config.dimensions or self.index.ntotal != len(self.chunks):
            raise ValueError("FAISS vectors do not match chunk metadata")
        return self

    def build(self):
        if self.path.exists():
            return self.load()
        self.chunks = [c for p in sorted(self.config.policy_dir.glob("*.md"))
                       for c in chunk_document(p, self.config.chunk_tokens, self.config.overlap_tokens)]
        vectors = np.stack([self.embedder.embed(c["text"]) for c in self.chunks])
        faiss.normalize_L2(vectors)
        self.index = faiss.IndexFlatIP(self.config.dimensions)
        self.index.add(vectors)
        self.config.index_root.mkdir(parents=True, exist_ok=True)
        # Publish only complete index versions. A failed build leaves no current index.
        with tempfile.TemporaryDirectory(dir=self.config.index_root) as temporary:
            staging = Path(temporary) / "complete"
            staging.mkdir()
            faiss.write_index(self.index, str(staging / "index.faiss"))
            (staging / "chunks.jsonl").write_text(
                "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in self.chunks), encoding="utf-8")
            write_json(staging / "manifest.json", {
                "index_id": self.index_id, "signature": self.signature,
                "chunk_count": len(self.chunks),
                "embedding_input_tokens": self.embedder.input_tokens,
                "hashes": {n: digest((staging / n).read_bytes()) for n in ("index.faiss", "chunks.jsonl")},
            })
            staging.rename(self.path)
        return self

    def search(self, query, count, doc_ids=None):
        if self.index is None:
            raise RuntimeError("Load or build the policy index first")
        vector = np.asarray([self.embedder.embed(query)], dtype="float32")
        faiss.normalize_L2(vector)
        # Search all vectors, then filter: corpus is small; no filtered top-k starvation.
        scores, ids = self.index.search(vector, self.index.ntotal)
        hits = []
        for score, i in zip(scores[0], ids[0]):
            if i < 0:
                continue
            chunk = self.chunks[int(i)]
            if doc_ids and chunk["doc_id"] not in doc_ids:
                continue
            hits.append({**chunk, "score": float(score)})
            if len(hits) == count:
                break
        return hits
