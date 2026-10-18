import json
import unittest

from rag.claims import fallback_offer, response_contract, validate_claims


CUSTOMER = {"loyalty_tier": "Silver", "top_categories": ["Home", "Beauty"], "tier_verified": False}
SELECTED = {
    "benefit_id": "points", "tier": "Silver", "eligibility": "conditional-tier",
    "conditions": ["Current Silver membership under trailing 12-month spend policy", "Qualifying merchandise spend"],
    "approved_claim": "If your current tier is Silver, you earn 1.25 points per $1 of qualifying merchandise spend.",
}


class ClaimValidationTests(unittest.TestCase):
    def payload(self):
        return {
            "benefit_id": "points", "category": "Home",
            "eligibility_condition": {"tier": "Silver", "status": "conditional-tier", "conditions": list(SELECTED["conditions"])},
            "offer_text": SELECTED["approved_claim"] + " Come back to NorthStar to explore Home.",
        }

    def errors(self, payload):
        return validate_claims(json.dumps(payload), CUSTOMER, SELECTED)[1]

    def test_valid_payload_returns_customer_copy_without_metadata(self):
        parsed, errors = validate_claims(json.dumps(self.payload()), CUSTOMER, SELECTED)
        self.assertEqual([], errors)
        self.assertEqual(self.payload(), parsed)
        self.assertEqual([], self.errors(fallback_offer(CUSTOMER, SELECTED)))
        self.assertFalse(response_contract(CUSTOMER, SELECTED)["schema"]["additionalProperties"])

    def test_cannot_change_incentive_tier_or_verification(self):
        for field, value in [("benefit_id", "early_access"), ("category", "Outdoor")]:
            payload = self.payload()
            payload[field] = value
            with self.subTest(field=field):
                self.assertTrue(self.errors(payload))
        for field, value in [("tier", "Gold"), ("status", "verified-tier"), ("conditions", SELECTED["conditions"][:1])]:
            payload = self.payload()
            payload["eligibility_condition"][field] = value
            with self.subTest(field=field):
                self.assertTrue(self.errors(payload))

    def test_valid_metadata_cannot_hide_unsupported_prose(self):
        original = self.payload()["offer_text"]
        variations = [
            original.replace("1.25", "2"),
            original.replace("If your current tier is Silver,", "As a Gold member,"),
            original + " A complimentary replacement is included.",
            SELECTED["approved_claim"] + " Discover what's new in Home.",
            original.replace("explore Home", "explore Beauty"),
            original.replace("qualifying merchandise spend", "every purchase"),
        ]
        for text in variations:
            with self.subTest(text=text):
                self.assertTrue(self.errors({**self.payload(), "offer_text": text}))

    def test_rejects_wrong_types_unknown_fields_and_missing_fields(self):
        for field in self.payload():
            payload = self.payload()
            del payload[field]
            with self.subTest(missing=field):
                self.assertTrue(self.errors(payload))
        for field, value in [("category", ["Home"]), ("benefit_id", True), ("offer_text", 1),
                             ("eligibility_condition", "Current Silver membership")]:
            with self.subTest(field=field):
                self.assertTrue(self.errors({**self.payload(), field: value}))
        self.assertTrue(self.errors({**self.payload(), "discount": 20}))
        payload = self.payload()
        payload["eligibility_condition"]["conditions"] = [True]
        self.assertTrue(self.errors(payload))
        payload = self.payload()
        payload["eligibility_condition"]["override"] = "approved"
        self.assertTrue(self.errors(payload))

    def test_json_is_not_repaired_or_coerced(self):
        valid = json.dumps(self.payload())
        invalid = ["not JSON", "```json\n" + valid + "\n```", valid[:-1], "[]", "null",
                   valid.replace('"benefit_id": "points"', '"benefit_id": "early_access", "benefit_id": "points"'),
                   valid.replace('"category": "Home"', '"category": NaN')]
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertTrue(validate_claims(raw, CUSTOMER, SELECTED)[1])
        self.assertTrue(validate_claims(valid, CUSTOMER, None)[1])


if __name__ == "__main__":
    unittest.main()
