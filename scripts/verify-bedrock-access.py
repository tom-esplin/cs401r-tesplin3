"""Exercise the two Bedrock runtime capabilities used by Track B.

These are real billed requests (a short Claude response and one Titan embedding).
Compare these checks with your course's Pre-Lab instructions before submission.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--model-id", default="us.anthropic.claude-haiku-4-5-20251001-v1:0")
    parser.add_argument("--embedding-model-id", default="amazon.titan-embed-text-v2:0")
    parser.add_argument("--output", type=Path, default=Path("docs/bedrock-access-verification.txt"))
    args = parser.parse_args()
    config = Config(connect_timeout=10, read_timeout=60,
                    retries={"mode": "standard", "max_attempts": 2})
    session = boto3.Session(region_name=args.region)
    runtime = session.client("bedrock-runtime", config=config)
    lines = ["NorthStar Lab 3 - Bedrock runtime access verification",
             f"UTC: {datetime.now(timezone.utc).isoformat()}", f"Region: {args.region}",
             "Scope: Claude generation and Titan embeddings used by Track B.",
             "Check definitions are recorded below; compare with the Pre-Lab handout."]
    failed = False
    try:
        identity = session.client("sts", config=config).get_caller_identity()
        lines.append(f"Account: {identity['Account']}")
    except Exception as exc:
        failed = True
        lines.append(f"Identity: FAIL - {type(exc).__name__}: {exc}")
    for label, model_id, invoke in [
        ("CHECK 1: Claude generation", args.model_id,
         lambda: runtime.converse(
             modelId=args.model_id,
             messages=[{"role": "user", "content": [{"text": "Reply with exactly: access verified"}]}],
             inferenceConfig={"maxTokens": 32, "temperature": 0})),
        ("CHECK 2: Titan embeddings", args.embedding_model_id,
         lambda: runtime.invoke_model(
             modelId=args.embedding_model_id, contentType="application/json", accept="application/json",
             body=json.dumps({"inputText": "NorthStar policy access check", "dimensions": 1024,
                              "normalize": True}))),
    ]:
        lines.extend(["", label, f"Model: {model_id}"])
        try:
            response = invoke()
            if "body" in response:
                payload = json.loads(response["body"].read())
                vector = payload.get("embedding", [])
                if len(vector) != 1024:
                    raise ValueError(f"Expected 1024 dimensions; received {len(vector)}")
                detail = f"Embedding dimensions: {len(vector)}"
            else:
                content = response["output"]["message"]["content"]
                result = " ".join(block.get("text", "") for block in content).strip()
                if not result:
                    raise ValueError("Empty generation response")
                detail = f"Response: {result}"
            lines.extend(["Result: PASS", detail,
                          f"Request ID: {response['ResponseMetadata']['RequestId']}"])
        except Exception as exc:
            failed = True
            lines.append(f"Result: FAIL - {type(exc).__name__}: {exc}")
    lines.extend(["", "Overall runtime checks: " + ("FAIL" if failed else "PASS")])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
