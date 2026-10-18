from dataclasses import asdict, dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    region: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    embedding_model: str = "amazon.titan-embed-text-v2:0"
    generation_model: str = os.getenv("RAG_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    feature_group: str = "northstar-dev-customer-features"
    dimensions: int = 1024
    chunk_tokens: int = 400
    overlap_tokens: int = 60
    top_k: int = 8
    strategy: str = "combined"
    policy_dir: Path = ROOT / "northstar-policy-docs"
    index_root: Path = ROOT / "artifacts/rag/indexes"
    run_root: Path = ROOT / "evaluation_results/rag"

    def __post_init__(self):
        if not 0 <= self.overlap_tokens < self.chunk_tokens:
            raise ValueError("Require 0 <= overlap_tokens < chunk_tokens")
        if self.strategy not in {"benefits", "constraints", "combined"}:
            raise ValueError("Unknown retrieval strategy")
        if self.top_k < 2:
            raise ValueError("top_k must be at least 2 for two-pass retrieval")

    def as_dict(self):
        return {k: str(v) if isinstance(v, Path) else v for k, v in asdict(self).items()}


def aws_client(service, region):
    import boto3
    from botocore.config import Config as AWSConfig
    return boto3.client(service, region_name=region, config=AWSConfig(
        connect_timeout=10, read_timeout=90,
        retries={"mode": "standard", "max_attempts": 3},
    ))
