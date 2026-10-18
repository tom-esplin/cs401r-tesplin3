"""Validate model claims and rendered copy against the selected policy benefit.

The model chooses a known category and an approved invitation. It cannot change
the incentive, remove eligibility conditions, or hide extra promises in prose.
Only the validated offer text is returned to the customer.
"""
import json

CONTRACT_VERSION = "structured-claims-v1"
GENERATION_FORMAT = "bedrock-json-schema"
FIELDS = {"benefit_id", "category", "eligibility_condition", "offer_text"}
INVITATIONS = (
    "Come back to NorthStar to explore {category}.",
    "Visit NorthStar to shop {category}.",
    "Explore {category} on your next NorthStar visit.",
)


def decoder_schema():
    """Stable transport schema; per-customer authorization stays in our validator.

    One schema can reuse Bedrock's compiled grammar across customers. Binding
    eligibility and copy to each customer's selected benefit is a separate check.
    """
    from .customers import CATEGORIES
    return {
        "type": "object", "additionalProperties": False, "required": sorted(FIELDS),
        "properties": {
            "benefit_id": {"type": "string", "enum": ["points", "early_access", "gear_repair"]},
            "category": {"type": "string", "enum": sorted(CATEGORIES)},
            "eligibility_condition": {
                "type": "object", "additionalProperties": False,
                "required": ["tier", "status", "conditions"],
                "properties": {
                    "tier": {"type": "string", "enum": ["Bronze", "Silver", "Gold", "Platinum"]},
                    "status": {"type": "string", "enum": ["conditional-tier", "verified-tier"]},
                    "conditions": {"type": "array", "items": {"type": "string"}},
                },
            },
            "offer_text": {"type": "string"},
        },
    }


def eligibility_condition(selected):
    return {"tier": selected["tier"], "status": selected["eligibility"],
            "conditions": list(selected["conditions"])}


def approved_offers(customer, selected):
    return [
        {"category": category,
         "offer_text": selected["approved_claim"] + " " + template.format(category=category)}
        for category in dict.fromkeys(customer["top_categories"])
        for template in INVITATIONS
    ]


def response_contract(customer, selected):
    """JSON Schema plus approved copy options, also supplied to generation."""
    choices = approved_offers(customer, selected)
    return {
        "contract_version": CONTRACT_VERSION,
        "schema": {
            "type": "object", "additionalProperties": False,
            "required": sorted(FIELDS),
            "properties": {
                "benefit_id": {"const": selected["benefit_id"]},
                "category": {"enum": list(dict.fromkeys(customer["top_categories"]))},
                "eligibility_condition": {"const": eligibility_condition(selected)},
                "offer_text": {"enum": [choice["offer_text"] for choice in choices]},
            },
        },
        "approved_offers": choices,
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")


def validate_claims(raw, customer, selected):
    """Return (decoded payload, errors); do not coerce types or repair JSON.

The schema checks the envelope. Policy binding and the category/text pairing
are checked separately, so a syntactically valid response still needs approval.
"""
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError) as error:
        return None, [f"Invalid structured JSON: {error}"]
    if not isinstance(payload, dict):
        return payload, ["Structured response must be a JSON object"]
    errors = []
    if set(payload) != FIELDS:
        errors.append("Response must contain exactly benefit_id, category, eligibility_condition, and offer_text")
    for name in ("benefit_id", "category", "offer_text"):
        if not isinstance(payload.get(name), str) or not payload[name].strip():
            errors.append(f"{name} must be a nonempty string")
    condition = payload.get("eligibility_condition")
    if not isinstance(condition, dict) or set(condition) != {"tier", "status", "conditions"}:
        errors.append("eligibility_condition must contain exactly tier, status, and conditions")
    elif (not isinstance(condition["tier"], str) or not isinstance(condition["status"], str)
          or not isinstance(condition["conditions"], list)
          or any(not isinstance(item, str) for item in condition["conditions"])):
        errors.append("Eligibility fields have invalid types")
    if errors:
        return payload, errors
    if selected is None:
        return payload, ["No policy benefit was authorized"]
    if payload["benefit_id"] != selected["benefit_id"]:
        errors.append("benefit_id does not match the preselected policy benefit")
    if condition != eligibility_condition(selected):
        errors.append("Eligibility does not match the authorized tier, verification status, and conditions")
    if payload["category"] not in customer["top_categories"]:
        errors.append("Category is not a known customer preference")
    allowed = {choice["offer_text"] for choice in approved_offers(customer, selected)
               if choice["category"] == payload["category"]}
    if payload["offer_text"] not in allowed:
        errors.append("offer_text must preserve the approved benefit and use an approved invitation for its declared category")
    return payload, errors


def fallback_offer(customer, selected):
    """Use the same contract for fallback copy; never bypass validation."""
    choice = approved_offers(customer, selected)[0]
    payload = {"benefit_id": selected["benefit_id"], **choice,
               "eligibility_condition": eligibility_condition(selected)}
    validated, errors = validate_claims(json.dumps(payload), customer, selected)
    if errors:
        raise ValueError("Invalid application fallback: " + "; ".join(errors))
    return validated
