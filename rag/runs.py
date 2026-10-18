"""Append-only case traces and explicit completed/failed run manifests."""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import subprocess
import uuid

from .config import ROOT
from .claims import CONTRACT_VERSION, GENERATION_FORMAT
from .index import digest, write_json
from .prompts import SYSTEM_PROMPT


class RunRecorder:
    def __init__(self, config, index_id, mode, judge_model=None):
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8]
        self.path = config.run_root / self.run_id
        self.path.mkdir(parents=True)
        self.cases = []
        self.metadata = {"run_id": self.run_id, "started_at": datetime.now(timezone.utc).isoformat(),
                         "status": "running", "mode": mode, "config": config.as_dict(),
                         "index_id": index_id, "prompt_hash": digest(SYSTEM_PROMPT.encode()),
                         "judge_model": judge_model}
        self.metadata["validation_contract"] = CONTRACT_VERSION
        self.metadata["generation_format"] = GENERATION_FORMAT
        self.metadata["source_hashes"] = {
            str(path.relative_to(ROOT)): digest(path.read_bytes())
            for path in sorted((ROOT / "rag").glob("*.py"))
        }
        self.metadata["source_hashes"]["evaluation/evaluation_harness.py"] = digest(
            (ROOT / "evaluation/evaluation_harness.py").read_bytes())
        (self.path / "system_prompt.txt").write_text(SYSTEM_PROMPT, encoding="utf-8")
        try:
            self.metadata["git_revision"] = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
            self.metadata["git_dirty"] = bool(subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True))
        except (OSError, subprocess.CalledProcessError):
            self.metadata["git_revision"] = None
        self.logger = logging.getLogger(f"rag.{self.run_id}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.handler = logging.FileHandler(self.path / "run.log", encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(self.handler)
        write_json(self.path / "run.json", self.metadata)
        (self.path / "cases.jsonl").touch()
        self.logger.info("Started %s", mode)

    def record_case(self, trace):
        record = {"case_id": f"case-{len(self.cases) + 1:03d}", **trace}
        with (self.path / "cases.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.cases.append(record)
        self.logger.info("Saved %s; fallback=%s", record["case_id"], record.get("fallback"))

    def finish(self, scores=None, error=None, embedding_tokens=None):
        summary = {"case_count": len(self.cases), "fallback_count": sum(c.get("fallback", False) for c in self.cases),
                   "generation_usage": {}, "embedding_input_tokens": embedding_tokens,
                   "latency_seconds": [c.get("latency_seconds") for c in self.cases],
                   "evaluation_performed": scores is not None}
        attempts = [attempt for case in self.cases for attempt in case.get("attempts", [])]
        summary["model_response_count"] = len(attempts)
        summary["rejected_model_response_count"] = sum(bool(attempt.get("validation_errors")) for attempt in attempts)
        summary["validated_model_case_count"] = sum(
            not case.get("fallback", False) and case.get("structured_offer") is not None for case in self.cases)
        for case in self.cases:
            for key, count in case.get("generation_usage", {}).items():
                summary["generation_usage"][key] = summary["generation_usage"].get(key, 0) + count
        if scores is not None:
            scores = scores.copy()
            if len(scores) != len(self.cases):
                raise ValueError("Evaluation rows do not match generated cases")
            scores.insert(0, "case_id", [c["case_id"] for c in self.cases])
            scores.to_csv(self.path / "scores.csv", index=False)
            targets = {"faithfulness": .80, "answer_relevancy": .75, "context_recall": .70}
            summary["metrics"] = {}
            for metric, target in targets.items():
                values = scores[metric] if metric in scores else None
                valid = bool(values is not None and len(values) > 0 and values.notna().all())
                mean = float(values.mean()) if valid else None
                summary["metrics"][metric] = {"mean": mean, "target": target,
                                                "passed": valid and mean >= target}
        self.metadata.update(status="failed" if error else "completed",
                             ended_at=datetime.now(timezone.utc).isoformat())
        if error:
            self.metadata["error"] = str(error)
            self.logger.error("Failed: %s", error)
        else:
            self.logger.info("Completed")
        try:
            write_json(self.path / "summary.json", summary)
            write_json(self.path / "run.json", self.metadata)
        finally:
            self.handler.close()
            self.logger.removeHandler(self.handler)
