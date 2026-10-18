"""Run with `python -m rag --help` from the repository root."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

from .config import Config
from .index import PolicyIndex, write_json
from .pipeline import OfferPipeline
from .runs import RunRecorder


def parser():
    cli = argparse.ArgumentParser(description="NorthStar policy RAG")
    cli.add_argument("--region", default=Config.region)
    cli.add_argument("--model-id", default=Config.generation_model)
    cli.add_argument("--strategy", choices=["benefits", "constraints", "combined"], default="combined")
    cli.add_argument("--top-k", type=int, default=8)
    cli.add_argument("--run-root", type=Path, default=Config.run_root)
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("build-index", help="Embed policies once; reuse an existing matching index")
    evaluate = commands.add_parser("evaluate", help="Run the four supplied profiles")
    evaluate.add_argument("--skip-judge", action="store_true", help="Generate traces without RAGAS; not a passing evaluation")
    evaluate.add_argument("--judge-model-id", default=None)
    offer = commands.add_parser("offer", help="Generate from a profile JSON or live Feature Store")
    source = offer.add_mutually_exclusive_group(required=True)
    source.add_argument("--profile", type=Path)
    source.add_argument("--customer-id")
    offer.add_argument("--categories", nargs="+", help="Override categories derived from the Lab 2 purchase snapshot")
    offer.add_argument("--churn-probability", type=float, help="Override prediction computed with the saved churn model")
    offer.add_argument("--question", default="Generate a personalized retention offer for this at-risk customer.")
    return cli


def main():
    # Windows redirected consoles may default to a legacy code page; the
    # supplied harness and policy excerpts contain Unicode punctuation.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    cli = parser()
    args = cli.parse_args()
    config = replace(Config(), region=args.region, generation_model=args.model_id,
                     strategy=args.strategy, top_k=args.top_k, run_root=args.run_root)
    index = PolicyIndex(config)
    judge_model = getattr(args, "judge_model_id", None) or config.generation_model
    recorder = RunRecorder(config, index.index_id, args.command,
                           judge_model if args.command == "evaluate" and not args.skip_judge else None)
    print(f"Run records: {recorder.path}", flush=True)
    embedding_start = index.embedder.input_tokens
    scores = None
    try:
        if args.command == "build-index":
            index.build()
            print(f"Index: {index.path} ({len(index.chunks)} chunks)")
        else:
            if not index.path.exists():
                raise ValueError("No compatible index. Run `python -m rag build-index` first")
            index.load()
            pipeline = OfferPipeline(index, config, recorder=recorder)
            if args.command == "evaluate":
                from evaluation.evaluation_harness import OFFER_TEST_CASES, RAGEvaluator
                if args.skip_judge:
                    for case in OFFER_TEST_CASES:
                        result = pipeline({**case.customer_context, "customer_id": case.customer_id}, case.question)
                        print(f"{case.customer_id}: {result['answer']}", flush=True)
                    recorder.finish(embedding_tokens=index.embedder.input_tokens - embedding_start)
                else:
                    evaluator = RAGEvaluator(pipeline, bedrock_model_id=judge_model, region=config.region)
                    scores = evaluator.run(OFFER_TEST_CASES)
                    write_json(recorder.path / "judge_traces.json", evaluator.last_traces)
                    recorder.finish(scores=scores, embedding_tokens=index.embedder.input_tokens - embedding_start)
                print(f"Cases: {len(recorder.cases)}; fallbacks: {sum(case.get('fallback', False) for case in recorder.cases)}")
                return 0
            if args.command == "offer":
                if args.profile:
                    customer = json.loads(args.profile.read_text(encoding="utf-8-sig"))
                else:
                    from .customers import load_customer
                    customer = load_customer(args.customer_id, config, top_categories=args.categories,
                                             churn_probability=args.churn_probability)
                    recorder.metadata["customer_source"] = "online-feature-store"
                    recorder.metadata["customer_id"] = args.customer_id
                    customer["customer_id"] = args.customer_id
                print(pipeline(customer, args.question)["answer"])
        recorder.finish(embedding_tokens=index.embedder.input_tokens - embedding_start)
        return 0
    except Exception as error:
        recorder.finish(scores=scores, error=error, embedding_tokens=index.embedder.input_tokens - embedding_start)
        print(f"ERROR: {error}\nPartial records: {recorder.path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
