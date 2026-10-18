"""Choose an incentive from indexed policy before generating marketing copy."""
import re

TIERS = ("Bronze", "Silver", "Gold", "Platinum")


class BenefitSelector:
    def __init__(self, chunks):
        self.chunks = chunks

    def evidence(self, section):
        return [c for c in self.chunks if c["doc_id"] == "POL-LOY-011" and c["section"] == section]

    def tier_value(self, label, tier):
        values = set()
        for chunk in self.evidence("## 4. Tier Benefits"):
            columns = []
            for line in chunk["text"].splitlines():
                cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
                if len(cells) == 5 and cells[0] == "Benefit":
                    columns = cells[1:]
                if len(cells) == 5 and cells[0] == label and set(columns) == set(TIERS):
                    values.add(cells[1 + columns.index(tier)])
        return values.pop() if len(values) == 1 else None

    def plan(self, customer):
        tier = customer["loyalty_tier"]
        verified = customer.get("tier_verified", False)
        prefix = f"As a {tier} member, " if verified else f"If your current tier is {tier}, "
        candidates, excluded = [], []

        def add(name, statement, sections, conditions=(), exclusions=()):
            evidence = []
            for section in sections:
                found = self.evidence(section)
                if not found:
                    excluded.append({"benefit_id": name, "reason": f"Missing policy evidence: {section}"})
                    return
                evidence.extend(found)
            candidates.append({
                "benefit_id": name, "tier": tier,
                "eligibility": "verified-tier" if verified else "conditional-tier",
                "conditions": [f"Current {tier} membership under trailing 12-month spend policy"] + list(conditions),
                "exclusions": list(exclusions), "approved_claim": prefix + statement + ".",
                "citations": [{"doc_id": "POL-LOY-011", "section": section} for section in sections],
                "source_chunk_ids": list(dict.fromkeys(c["id"] for c in evidence)),
            })

        source = "## 4. Tier Benefits"
        rate = self.tier_value("Points earn rate", tier)
        # Multipliers can be interpreted as points/$1 only while the base rate
        # remains 1 point/$1. Missing or changed definitions fail closed.
        base_supported = any(re.search(
            r"Members earn\s+\*\*1 point per \$1\*\*\s+of qualifying merchandise spend", c["text"])
            for c in self.evidence("## 3. Points"))
        if rate and re.fullmatch(r"\d+(?:\.\d+)?[×x]", rate) and base_supported:
            number = rate[:-1]
            noun = "point" if number == "1" else "points"
            add("points", f"you earn {number} {noun} per $1 of qualifying merchandise spend",
                [source, "## 3. Points"], conditions=["Qualifying merchandise spend"],
                exclusions=["No bonus promotion or existing points balance is implied"])
        else:
            excluded.append({"benefit_id": "points", "reason": "Cannot verify earn rate and base rate"})

        access = self.tier_value("Early access to sales", tier)
        if access and re.fullmatch(r"\d+ hours", access):
            add("early_access", f"your benefits include {access.replace(' hours', '-hour')} early access to sales",
                [source], exclusions=["No active sale or sale date is known"])

        repair = self.tier_value("Free gear repair", tier)
        if repair == "Unlimited":
            add("gear_repair", "your benefits include unlimited free gear repair", [source],
                exclusions=["No product replacement or new merchandise is promised"])
        elif repair and re.fullmatch(r"\d+ per year", repair):
            add("gear_repair", f"your benefits include {repair.split()[0]} free gear repairs per year", [source],
                conditions=["Annual entitlement, not a verified unused repair balance"],
                exclusions=["Do not claim how many repairs remain this year"])

        excluded.extend([
            {"benefit_id": "annual_gear_credit", "reason": "No verified remaining credit balance"},
            {"benefit_id": "birthday_reward", "reason": "No verified birthday eligibility"},
            {"benefit_id": "shipping", "reason": "Shipping incentive requires separate destination, subtotal and surcharge eligibility checks"},
            {"benefit_id": "return_window", "reason": "Purchase-time tier and item eligibility are not established"},
        ])
        if not candidates:
            return {"selected": None, "eligible_benefits": [], "excluded_benefits": excluded,
                    "selection_reason": "No incentive is supported by available policy evidence"}
        if tier == "Platinum":
            preference = ["early_access", "gear_repair", "points"]
            reason = "Prioritize exclusive access without assuming unused credit"
        elif tier == "Gold" and set(customer["top_categories"]) & {"Outdoor", "Footwear"}:
            preference = ["gear_repair", "points", "early_access"]
            reason = "Existing gear-repair entitlement matches known Outdoor/Footwear interests"
        else:
            preference = ["points", "early_access", "gear_repair"]
            reason = "Use the existing earn rate without assuming shipping eligibility or a new promotion"
        selected = min(candidates, key=lambda benefit: preference.index(benefit["benefit_id"]))
        return {"selected": selected, "eligible_benefits": candidates,
                "excluded_benefits": excluded, "selection_reason": reason}


def validate_invitation(text, customer):
    """Check copy separately; the benefit claim is rendered by application code."""
    issues = []
    if not text.strip() or len(re.split(r"(?<=[.!?])\s+", text.strip())) != 1:
        issues.append("Write one invitation sentence only")
    if not any(category.lower() in text.lower() for category in customer["top_categories"]):
        issues.append("Mention a supplied category")
    if re.search(r"\d|[$%]|\b(?:points?|shipping|returns?|repairs?|credit|discounts?|rewards?|tiers?|gold|silver|bronze|platinum|sales?|deals?|free|bonus|expires?|expiry|deadline|risk.free|new arrivals|in stock)\b", text, re.I):
        issues.append("Invitation must not add or repeat benefit, availability, or promotion claims")
    return issues
