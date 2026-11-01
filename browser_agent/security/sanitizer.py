import re

from browser_agent.security.data_classifier import classify_field


SENSITIVE_PATTERNS = [
    re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE),
    re.compile(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        re.IGNORECASE
    ),
    re.compile(r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b"),
]

FIELD_REF_PATTERN = re.compile(r"field_\d{4}")


def sanitize_text(text):
    if not isinstance(text, str):
        return ""

    sanitized = text

    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)

    return sanitized[:500]


def sanitize_observation(observation):
    """
    Build a privacy-preserving observation for external LLM use.

    PUBLIC and PERSONAL fields receive opaque references.
    CONFIDENTIAL and NEVER_SEND fields are excluded.
    Actual values and identifying metadata never leave the browser.
    """

    safe_fields = []

    for field in observation.get("input_fields", []):

        if not isinstance(field, dict):
            continue

        classification = classify_field(field)

        if classification not in {"PUBLIC", "PERSONAL"}:
            continue

        field_ref = field.get("field_ref")

        # Fail closed if the field reference is invalid.
        if not isinstance(field_ref, str):
            continue

        if not FIELD_REF_PATTERN.fullmatch(field_ref):
            continue

        safe_fields.append({
            "field_ref": field_ref,
            "category": classification,
            "type": sanitize_text(
                field.get("type", "text")
            ).lower(),
            "required": bool(field.get("required", False)),
            "disabled": bool(field.get("disabled", False))
        })

    return {
        "title": sanitize_text(observation.get("title", "")),

        "headings": [
            sanitize_text(item)
            for item in observation.get("headings", [])
            if isinstance(item, str)
        ][:30],

        "buttons": [
            {
                "text": sanitize_text(button.get("text", "")),
                "disabled": bool(button.get("disabled", False))
            }
            for button in observation.get("buttons", [])
            if isinstance(button, dict)
        ][:50],

        "links": [
            {
                "text": sanitize_text(link.get("text", "")),
                "visible": bool(link.get("visible", False))
            }
            for link in observation.get("links", [])
            if isinstance(link, dict)
        ][:50],

        "input_fields": safe_fields,

        "security": {
            "personal_values_included": False,
            "confidential_values_included": False,
            "authentication_values_included": False
        }
    }