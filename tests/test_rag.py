import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import numpy as np

from rag.config import Config
from rag.benefits import BenefitSelector, validate_invitation
from rag.claims import fallback_offer, validate_claims
from rag.customers import load_customer, validate_customer
from rag.index import PolicyIndex, chunk_document
from rag.pipeline import OfferPipeline, retrieve, validate_offer
from rag.runs import RunRecorder


PROFILE = {"churn_probability": .8, "loyalty_tier": "Gold", "top_categories": ["Outdoor"]}


class FakeEmbedder:
    input_tokens = 0

    def embed(self, text):
        return np.array([1, len(text) % 3 + 1, .5, .25], dtype="float32")


class FakeGeneration:
    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        answer = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return {"output": {"message": {"content": [{"text": answer}]}},
                "usage": {"inputTokens": 12, "outputTokens": 8}, "stopReason": "end_turn"}


class RAGTests(unittest.TestCase):
    def config(self, directory):
        root = Path(directory)
        policy = root / "policies"
        policy.mkdir()
        (policy / "loyalty.md").write_text(
            (Config().policy_dir / "loyalty-program-terms.md").read_text(encoding="utf-8"), encoding="utf-8")
        return replace(Config(), policy_dir=policy, index_root=root / "indexes",
                       run_root=root / "runs", dimensions=4)

    def test_roundtrip_and_integrity_and_policy_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            original = PolicyIndex(config, FakeEmbedder()).build()
            result = original.search("Gold rewards", 2)
            loaded = PolicyIndex(config, FakeEmbedder()).load()
            self.assertEqual(result, loaded.search("Gold rewards", 2))
            self.assertEqual([], loaded.search("Gold rewards", 2, {"missing"}))
            file = config.policy_dir / "loyalty.md"
            file.write_text(file.read_text(encoding="utf-8") + "New restriction", encoding="utf-8")
            self.assertNotEqual(original.index_id, PolicyIndex(config, FakeEmbedder()).index_id)
            with (original.path / "chunks.jsonl").open("a") as stream:
                stream.write("corruption")
            with self.assertRaisesRegex(ValueError, "integrity"):
                loaded.load()

    def test_table_headers_repeated_and_token_limit(self):
        import tiktoken
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.md"
            path.write_text("## Benefits\n| Tier | Benefit |\n|---|---|\n" + "| Gold | 1.5x points |\n" * 30, encoding="utf-8")
            chunks = list(chunk_document(path, 100, 10))
            self.assertGreater(len(chunks), 1)
            for chunk in chunks:
                self.assertIn("| Tier | Benefit |", chunk["text"])
                self.assertLessEqual(len(tiktoken.get_encoding("cl100k_base").encode(chunk["text"])), 100)

    def test_live_features_require_explicit_categories_and_prediction(self):
        class Client:
            def get_record(self, **kwargs):
                return {"Record": [{"FeatureName": "loyalty_tier", "ValueAsString": "Gold"}]}
        customer = load_customer("CUST-1", Config(), top_categories=["Outdoor"],
                                 churn_probability=.8, client=Client())
        self.assertFalse(customer["tier_verified"])
        with self.assertRaisesRegex(ValueError, "top_categories"):
            validate_customer({**PROFILE, "top_categories": []})
        with self.assertRaisesRegex(ValueError, "churn_probability"):
            validate_customer({**PROFILE, "churn_probability": float("nan")})
        self.assertNotIn("email", validate_customer({**PROFILE, "email": "private@example.com"}))

    def test_policy_checks_and_failed_generation_fallback(self):
        bad = "Enjoy Outdoor with free expedited shipping and a 60-day return window. Shop now."
        issues = validate_offer(bad, PROFILE, ["Policy"])
        self.assertTrue(any("expedited" in i for i in issues))
        self.assertTrue(any("Platinum" in i for i in issues))
        self.assertTrue(any("conditional" in i for i in issues))
        wrong_points = "If your current tier is Gold, enjoy 2x points on Outdoor. Shop today."
        self.assertTrue(any("multiplier" in i for i in validate_offer(wrong_points, PROFILE, ["Policy"])))
        shipping = "If your current tier is Gold, enjoy free standard shipping on Outdoor and free return shipping. Shop today."
        self.assertTrue(any("geographic" in i for i in validate_offer(shipping, PROFILE, ["Policy"])))
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            index = PolicyIndex(config, FakeEmbedder()).build()
            recorder = RunRecorder(config, index.index_id, "test")
            pipeline = OfferPipeline(index, config, client=FakeGeneration(bad), recorder=recorder)
            result = pipeline(PROFILE, "Make an offer")
            self.assertTrue(pipeline.last_trace["fallback"])
            self.assertNotIn("free expedited", result["answer"])
            self.assertEqual(2, len(pipeline.last_trace["attempts"]))
            recorder.finish(error=RuntimeError("judge failed"))
            manifest = json.loads((recorder.path / "run.json").read_text())
            self.assertEqual("failed", manifest["status"])
            self.assertEqual(1, len((recorder.path / "cases.jsonl").read_text().splitlines()))
            summary = json.loads((recorder.path / "summary.json").read_text())
            self.assertEqual(2, summary["rejected_model_response_count"])
            self.assertEqual(0, summary["validated_model_case_count"])

    def test_all_retrieval_strategies_and_accepted_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            index = PolicyIndex(config, FakeEmbedder()).build()
            for strategy in ("benefits", "constraints", "combined"):
                queries, hits = retrieve(index, PROFILE, "Make an offer", strategy, 4)
                self.assertTrue(queries)
                self.assertTrue(hits)
                self.assertEqual(len(hits), len({h["id"] for h in hits}))
            invitation = "Come back to NorthStar to explore Outdoor."
            payload = fallback_offer(PROFILE, BenefitSelector(index.chunks).plan(PROFILE)["selected"])
            pipeline = OfferPipeline(index, config, client=FakeGeneration(payload))
            result = pipeline(PROFILE, "Make an offer")
            selected = pipeline.last_trace["benefit_plan"]["selected"]
            self.assertEqual(selected["approved_claim"] + " " + invitation, result["answer"])
            self.assertEqual("gear_repair", selected["benefit_id"])
            self.assertFalse(pipeline.last_trace["fallback"])

    def test_selection_is_tier_specific_and_preserves_uncertain_eligibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = PolicyIndex(self.config(tmp), FakeEmbedder()).build()
            selector = BenefitSelector(index.chunks)
            for tier, expected in [("Bronze", "points"), ("Silver", "points"),
                                   ("Gold", "gear_repair"), ("Platinum", "early_access")]:
                plan = selector.plan({**PROFILE, "loyalty_tier": tier})
                self.assertEqual(expected, plan["selected"]["benefit_id"])
                self.assertTrue(plan["selected"]["approved_claim"].startswith(f"If your current tier is {tier},"))
                self.assertEqual("conditional-tier", plan["selected"]["eligibility"])
                self.assertTrue(plan["selected"]["source_chunk_ids"])
                self.assertNotIn("annual_gear_credit", [b["benefit_id"] for b in plan["eligible_benefits"]])
            silver = selector.plan({**PROFILE, "loyalty_tier": "Silver", "total_lifetime_value": 99999})
            self.assertIn("1.25 points", silver["selected"]["approved_claim"])
            verified = selector.plan({**PROFILE, "tier_verified": True})
            self.assertEqual("verified-tier", verified["selected"]["eligibility"])

    def test_missing_or_changed_policy_does_not_authorize_benefits(self):
        self.assertIsNone(BenefitSelector([]).plan(PROFILE)["selected"])
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            index = PolicyIndex(config, FakeEmbedder()).build()
            # Reordered table columns must still resolve Silver's actual rate.
            table = "| Benefit | Platinum | Gold | Silver | Bronze |\n| Points earn rate | 2× | 1.5× | 1.25× | 1× |"
            for chunk in index.chunks:
                if chunk["section"] == "## 4. Tier Benefits":
                    chunk["text"] = table
            selector = BenefitSelector(index.chunks)
            plan = selector.plan({**PROFILE, "loyalty_tier": "Silver"})
            self.assertIn("1.25 points", plan["selected"]["approved_claim"])
            for chunk in index.chunks:
                if chunk["section"] == "## 3. Points":
                    chunk["text"] = chunk["text"].replace("**1 point per $1**", "**2 points per $1**")
            self.assertIsNone(selector.plan({**PROFILE, "loyalty_tier": "Silver"})["selected"])

    def test_invitation_cannot_add_a_second_incentive(self):
        self.assertTrue(validate_invitation("Explore Outdoor with free shipping.", PROFILE))
        self.assertTrue(validate_invitation("Explore Outdoor and earn 9 points.", PROFILE))
        self.assertFalse(validate_invitation("Come back to explore Outdoor at NorthStar.", PROFILE))

    def test_no_supported_benefit_skips_generation(self):
        class EmptyIndex:
            chunks = []

            def search(self, *args):
                return []

        class NoGeneration:
            def converse(self, **kwargs):
                raise AssertionError("Do not generate an offer without a supported incentive")

        pipeline = OfferPipeline(EmptyIndex(), Config(), client=NoGeneration())
        result = pipeline(PROFILE, "Make an offer")
        self.assertTrue(pipeline.last_trace["fallback"])
        self.assertEqual([], pipeline.last_trace["attempts"])
        self.assertIn("Check your current", result["answer"])

    def test_selected_benefit_gets_original_evidence_if_search_misses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            index = PolicyIndex(config, FakeEmbedder()).build()
            index.search = lambda *args: []
            payload = fallback_offer(PROFILE, BenefitSelector(index.chunks).plan(PROFILE)["selected"])
            pipeline = OfferPipeline(index, config, client=FakeGeneration(payload))
            result = pipeline(PROFILE, "Make an offer")
            selected = pipeline.last_trace["benefit_plan"]["selected"]
            self.assertEqual(set(selected["source_chunk_ids"]), set(pipeline.last_trace["benefit_evidence_added"]))
            self.assertTrue(any("| Free gear repair |" in context for context in result["contexts"]))
            self.assertNotIn(selected["approved_claim"], result["contexts"])

    def test_invalid_claims_retry_then_accept_only_valid_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            index = PolicyIndex(config, FakeEmbedder()).build()
            selected = BenefitSelector(index.chunks).plan(PROFILE)["selected"]
            valid = fallback_offer(PROFILE, selected)
            invalid = {**valid, "benefit_id": "annual_gear_credit"}

            class CorrectingGeneration(FakeGeneration):
                def converse(self, **kwargs):
                    self.answer = invalid if not self.requests else valid
                    return super().converse(**kwargs)

            client = CorrectingGeneration(invalid)
            pipeline = OfferPipeline(index, config, client=client)
            result = pipeline(PROFILE, "Make an offer")
            self.assertFalse(pipeline.last_trace["fallback"])
            self.assertEqual(valid["offer_text"], result["answer"])
            self.assertEqual(2, len(client.requests))
            output_format = client.requests[0]["outputConfig"]["textFormat"]
            self.assertEqual("json_schema", output_format["type"])
            self.assertFalse(json.loads(output_format["structure"]["jsonSchema"]["schema"])["additionalProperties"])
            self.assertTrue(pipeline.last_trace["attempts"][0]["validation_errors"])
            self.assertEqual(valid, pipeline.last_trace["structured_offer"])

    def test_rejected_copy_uses_a_validated_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            index = PolicyIndex(config, FakeEmbedder()).build()
            selected = BenefitSelector(index.chunks).plan(PROFILE)["selected"]
            malicious = fallback_offer(PROFILE, selected)
            malicious["offer_text"] += " You also get a complimentary replacement."
            pipeline = OfferPipeline(index, config, client=FakeGeneration(malicious))
            result = pipeline(PROFILE, "Make an offer")
            self.assertTrue(pipeline.last_trace["fallback"])
            self.assertNotIn("replacement", result["answer"])
            final = pipeline.last_trace["structured_offer"]
            _, errors = validate_claims(json.dumps(final), PROFILE, selected)
            self.assertEqual([], errors)
            self.assertEqual(final["offer_text"], result["answer"])

    def test_partial_metric_results_do_not_pass(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(tmp)
            recorder = RunRecorder(config, "test-index", "evaluate")
            recorder.record_case({"answer": "Saved", "generation_usage": {}})
            recorder.record_case({"answer": "Saved", "generation_usage": {}})
            recorder.finish(scores=pd.DataFrame({"faithfulness": [1, float("nan")],
                                                 "answer_relevancy": [1, 1], "context_recall": [1, 1]}))
            summary = json.loads((recorder.path / "summary.json").read_text())
            self.assertFalse(summary["metrics"]["faithfulness"]["passed"])
            self.assertTrue(summary["metrics"]["context_recall"]["passed"])


if __name__ == "__main__":
    unittest.main()
