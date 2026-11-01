import re


FIELD_ALIASES = {
    "full_name": {
        "full name",
        "applicant name",
        "name of applicant",
        "applicant full name",
    },
    "email": {
        "email",
        "email address",
    },
    "registration_number": {
        "registration number",
        "vehicle registration number",
        "registration no",
        "rc number",
        "rc registration number",
    },
    "chassis_number": {
        "chassis number",
        "chassis no",
        "vehicle chassis number",
    },
    "engine_number": {
        "engine number",
        "engine no",
        "vehicle engine number",
    },
    "reason_for_duplicate": {
        "reason for duplicate",
        "reason for duplicate certificate",
    },
    "mobile_number": {
        "mobile number",
        "mobile",
        "phone number",
        "contact number",
    },
    "state": {
        "state",
    },
    "district": {
        "district",
    },
    "grievance_description": {
        "grievance description",
        "application description",
        "complaint description",
    },
}


ALLOWED_TYPES = {
    "text",
    "email",
    "tel",
}


def normalize(value):
    if not isinstance(value, str):
        return ""

    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)

    return " ".join(value.split())


def match_fields(observation, available_references):
    """
    Match observed browser fields to local service-data references.

    Only field metadata and reference names are used.
    Actual personal values are never accessed.
    """

    if not isinstance(observation, dict):
        raise ValueError("Invalid browser observation")

    fields = observation.get("input_fields")

    if not isinstance(fields, list):
        raise ValueError("Invalid input field collection")

    if not isinstance(available_references, (set, list, tuple)):
        raise ValueError("Invalid reference collection")

    available = set(available_references)

    matches = []
    used_fields = set()
    used_references = set()

    for reference, aliases in FIELD_ALIASES.items():

        if reference not in available:
            continue

        normalized_aliases = {
            normalize(alias) for alias in aliases
        }

        candidates = []

        for field in fields:

            if not isinstance(field, dict):
                continue

            field_ref = field.get("field_ref")

            if not isinstance(field_ref, str):
                continue

            if field_ref in used_fields:
                continue

            if field.get("disabled") is True:
                continue

            if field.get("type", "text") not in ALLOWED_TYPES:
                continue

            metadata = [
                field.get("label"),
                field.get("name"),
                field.get("id"),
                field.get("placeholder"),
            ]

            normalized_metadata = {
                normalize(item) for item in metadata
            }

            if normalized_aliases.intersection(normalized_metadata):
                candidates.append(field_ref)

        # Only accept an unambiguous one-to-one match.
        if len(candidates) == 1 and reference not in used_references:

            field_ref = candidates[0]

            matches.append({
                "field_ref": field_ref,
                "value_ref": reference,
            })

            used_fields.add(field_ref)
            used_references.add(reference)

    return matches