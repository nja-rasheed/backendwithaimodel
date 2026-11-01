import re


MAX_UNTRUSTED_TEXT_LENGTH = 10000


# These patterns identify common prompt-injection attempts.
# Detection is only an additional security signal, not a guarantee.
INJECTION_PATTERNS = {
    "instruction_override": [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(all\s+)?(previous|prior)\s+instructions",
        r"forget\s+(all\s+)?previous\s+instructions",
        r"override\s+(the\s+)?system\s+prompt",
        r"ignore\s+your\s+system\s+prompt",
    ],

    "secret_extraction": [
        r"reveal\s+(the\s+)?(system\s+prompt|hidden\s+instructions)",
        r"show\s+(me\s+)?(the\s+)?(api\s+key|password|secret)",
        r"reveal\s+(the\s+)?user('s)?\s+(password|credentials|secrets)",
        r"print\s+(all\s+)?(environment\s+variables|secrets)",
    ],

    "data_exfiltration": [
        r"send\s+.{0,80}\s+to\s+https?://",
        r"upload\s+.{0,80}\s+to\s+https?://",
        r"transmit\s+.{0,80}\s+to\s+https?://",
    ],

    "unauthorized_actions": [
        r"submit\s+without\s+(user\s+)?approval",
        r"bypass\s+(user\s+)?confirmation",
        r"execute\s+this\s+command",
        r"run\s+this\s+script",
    ],

    "concealment": [
        r"do\s+not\s+tell\s+the\s+user",
        r"hide\s+this\s+action\s+from\s+the\s+user",
        r"do\s+not\s+mention\s+this\s+instruction",
    ],
}


class PromptInjectionError(Exception):
    """Raised when untrusted webpage content is invalid."""
    pass


def detect_prompt_injection(text):
    """
    Detect common prompt-injection patterns.

    Returns a dictionary containing:
        suspicious: whether suspicious patterns were found
        categories: matching attack categories

    This is heuristic detection. It cannot identify every attack.
    """

    if not isinstance(text, str):
        raise PromptInjectionError(
            "Input must be a string"
        )

    detected_categories = []

    for category, patterns in INJECTION_PATTERNS.items():

        for pattern in patterns:

            if re.search(
                pattern,
                text,
                flags=re.IGNORECASE
            ):
                detected_categories.append(category)
                break

    return {
        "suspicious": bool(detected_categories),
        "categories": detected_categories
    }


def build_untrusted_content_block(text):
    """
    Wrap webpage text in a structured untrusted-data object.

    The webpage content is never treated as system instructions.
    """

    if not isinstance(text, str):
        raise PromptInjectionError(
            "Webpage content must be a string"
        )

    if len(text) > MAX_UNTRUSTED_TEXT_LENGTH:
        raise PromptInjectionError(
            "Webpage content exceeds maximum allowed length"
        )

    detection = detect_prompt_injection(text)

    return {
        "trust_level": "UNTRUSTED",
        "content": text,
        "suspicious": detection["suspicious"],
        "detected_categories": detection["categories"]
    }