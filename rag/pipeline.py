import json
import re
import time

from .config import aws_client
from .benefits import BenefitSelector
from .claims import CONTRACT_VERSION, GENERATION_FORMAT, decoder_schema, fallback_offer, response_contract, validate_claims
from .customers import validate_customer
from .prompts import SYSTEM_PROMPT


def retrieve(index, customer, question, strategy, top_k):
    tier = customer["loyalty_tier"]
    benefits = f"{question}\n{tier} loyalty tier benefits points earn rate shipping threshold return window annual gear credit early access repair"
    constraints = "final sale non-returnable expired offers retention offer 45 days single use restrictions Mexico expedited shipping exclusions"
    queries = []
    hits = []
    if strategy in {"benefits", "combined"}:
        filters = {"POL-LOY-011", "POL-SHP-007"} if strategy == "combined" else None
        count = top_k // 2 if strategy == "combined" else top_k
        queries.append({"text": benefits, "doc_ids": sorted(filters) if filters else None})
        candidates = index.search(benefits, len(index.chunks) if strategy == "combined" else count, filters)
        if strategy == "combined":
            priorities = ["## 4. Tier Benefits", "## 2. Tiers",
                          "### 4.1 Annual Gear Credit" if tier == "Platinum" else "## 3. Points",
                          "## 3. Points" if tier == "Platinum" else "### 3.1 Points Expiration"]
            candidates.sort(key=lambda h: priorities.index(h["section"]) if h["section"] in priorities else len(priorities))
        hits.extend(candidates[:count])
    if strategy in {"constraints", "combined"}:
        queries.append({"text": constraints, "doc_ids": None})
        # Retrieve extras so duplicate passages do not consume both passes' budget.
        candidates = index.search(constraints, len(index.chunks) if strategy == "combined" else top_k)
        if strategy == "combined":
            priorities = ["## 2. Free Shipping Thresholds", "## 4. Non-Returnable Merchandise",
                          "### 6.2 By Mail", "### 5.1 Retention Offers"]
            candidates.sort(key=lambda h: priorities.index(h["section"]) if h["section"] in priorities else len(priorities))
        seen = {h["id"] for h in hits}
        hits.extend(h for h in candidates if h["id"] not in seen)
    return queries, hits[:top_k]


def validate_offer(answer, customer, contexts):
    """Conservative checks, supplemented by RAGAS; not a proof of faithfulness."""
    issues = []
    lower = answer.lower()
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    if len(sentences) not in (2, 3):
        issues.append("Expected 2–3 sentences")
    if not any(c.lower() in lower for c in customer["top_categories"]):
        issues.append("Missing known product category")
    if re.search(r"\d+(?:\.\d+)?\s*%|\b(?:discount|promo code|bonus points)\b", lower):
        issues.append("Unapproved promotion")
    if "risk-free" in lower or "risk free" in lower:
        issues.append("Do not imply unrestricted returns; policy has exclusions")
    if re.search(r"points on (?:every purchase|all purchases)", lower):
        issues.append("Points apply to qualifying merchandise spend, not every purchase")
    if re.search(r"free\s+(?:expedited|overnight)", lower):
        issues.append("Unsupported expedited shipping benefit")
    if re.search(r"60[ -]day", lower) and customer["loyalty_tier"] != "Platinum":
        issues.append("60-day return window belongs to Platinum")
    if "free return shipping" in lower and customer["loyalty_tier"] in {"Bronze", "Silver"}:
        issues.append("Free return shipping requires Gold or Platinum")
    if "free standard shipping" in lower:
        if customer.get("country") == "Mexico":
            issues.append("Free shipping is unavailable for Mexico orders")
        elif customer.get("country") not in {"US", "Canada"} and not ("eligible" in lower and ("us" in lower or "canada" in lower)):
            issues.append("Missing geographic shipping condition")
        minimum = {"Bronze": "75", "Silver": "50"}.get(customer["loyalty_tier"])
        if minimum and f"${minimum}" not in lower:
            issues.append("Missing tier shipping minimum")
    if "unused" in lower and "credit" in lower:
        issues.append("Unused gear credit not verified")
    if re.search(r"points (?:never|do not|don't) expire", lower):
        issues.append("Points expire after 18 months without a qualifying purchase")
    if re.search(r"\b(?:close to|toward|towards|near) (?:gold|your next tier)\b", lower):
        issues.append("Cannot infer tier upgrade progress from lifetime spend")
    rates = {"Bronze": "1", "Silver": "1.25", "Gold": "1.5", "Platinum": "2"}
    for rate in re.findall(r"\b(\d+(?:\.\d+)?)\s*[x×]\s*(?:points|point)", lower):
        if rate != rates[customer["loyalty_tier"]]:
            issues.append("Points multiplier does not match customer tier")
    if not customer.get("tier_verified"):
        if not re.search(r"\bif\b.{0,90}\b" + customer["loyalty_tier"].lower() + r"\b", lower):
            issues.append("Approximate feature-store tier requires conditional wording")
    if not contexts:
        issues.append("No retrieved evidence")
    return issues


class OfferPipeline:
    def __init__(self, index, config, client=None, recorder=None):
        self.index, self.config = index, config
        self.client = client or aws_client("bedrock-runtime", config.region)
        self.recorder = recorder
        self.last_trace = None
        self.selector = BenefitSelector(index.chunks)

    def __call__(self, customer_context, question):
        return self.generate_offer(customer_context, question)

    def generate_offer(self, customer_context, question):
        started = time.perf_counter()
        customer = validate_customer(customer_context)
        queries, hits = retrieve(self.index, customer, question, self.config.strategy, self.config.top_k)
        plan = self.selector.plan(customer)
        selected = plan["selected"]
        evidence_added = []
        if selected:
            seen = {hit["id"] for hit in hits}
            for chunk in self.index.chunks:
                if chunk["id"] in selected["source_chunk_ids"] and chunk["id"] not in seen:
                    hits.append({**chunk, "retrieval_reason": "selected-benefit evidence"})
                    evidence_added.append(chunk["id"])
                    seen.add(chunk["id"])
        # Faithfulness judges need the same customer facts the generator sees.
        contexts = ["Actual offer request: " + question +
                    "\nCustomer profile (tier is approximate unless verified): " + json.dumps(customer)]
        contexts.extend(hit["text"] for hit in hits)
        contract = response_contract(customer, selected) if selected else None
        prompt = json.dumps({"customer": customer, "request": question,
                             "selected_incentive": selected,
                             "response_contract": contract,
                             "policy_excerpts": contexts}, ensure_ascii=False)
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        attempts = []
        usage = {}
        answer = ""
        structured_offer = None
        issues = [] if selected else ["No supported incentive"]
        for attempt in range(2 if selected else 0):
            response = self.client.converse(
                modelId=self.config.generation_model,
                system=[{"text": SYSTEM_PROMPT}], messages=messages,
                inferenceConfig={"maxTokens": 600, "temperature": 0},
                outputConfig={"textFormat": {"type": "json_schema", "structure": {"jsonSchema": {
                    "name": "northstar_retention_offer",
                    "description": "Return a structured retention offer for application validation",
                    "schema": json.dumps(decoder_schema(), sort_keys=True),
                }}}},
            )
            content = response["output"]["message"]["content"]
            raw = " ".join(block["text"] for block in content if "text" in block).strip()
            payload, issues = validate_claims(raw, customer, selected)
            if response.get("stopReason") != "end_turn":
                issues.append("Generation did not finish normally")
            for name, count in response.get("usage", {}).items():
                if isinstance(count, (int, float)):
                    usage[name] = usage.get(name, 0) + count
            attempts.append({"raw_response": raw, "structured_offer": payload, "validation_errors": issues,
                             "stop_reason": response.get("stopReason")})
            if not issues:
                structured_offer = payload
                answer = payload["offer_text"]
                break
            messages += [{"role": "assistant", "content": [{"text": raw or "{}"}]},
                         {"role": "user", "content": [{"text": "Return a corrected JSON object matching the response contract. Fix: " + "; ".join(issues)}]}]
        fallback = bool(issues) or selected is None
        if fallback:
            category = customer["top_categories"][0]
            if selected:
                structured_offer = fallback_offer(customer, selected)
                answer = structured_offer["offer_text"]
            else:
                answer = f"Explore {category} on your next NorthStar visit. Check your current Summit Rewards benefits and eligibility before shopping."
        trace = {
            "customer_id": customer_context.get("customer_id"),
            "provenance": customer_context.get("_provenance"),
            "customer_context": customer, "question": question, "queries": queries,
            "retrieved_chunks": hits, "contexts": contexts, "answer": answer,
            "attempts": attempts, "fallback": fallback, "validation_errors": issues,
            "benefit_plan": plan, "benefit_evidence_added": evidence_added,
            "validation_contract": CONTRACT_VERSION, "response_contract": contract,
            "generation_format": GENERATION_FORMAT,
            "structured_offer": structured_offer,
            "generation_usage": usage, "latency_seconds": time.perf_counter() - started,
        }
        self.last_trace = trace
        if self.recorder:
            self.recorder.record_case(trace)
        return {"answer": answer, "contexts": contexts}
