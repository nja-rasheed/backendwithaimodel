class ValueProviderError(Exception):
    """Raised when a local value cannot be safely resolved."""
    pass


class LocalValueProvider:
    """
    Provides explicitly approved local values to trusted execution code.

    Actual values must never be included in LLM prompts or audit logs.
    """

    ALLOWED_REFERENCES = {
        # Existing references
        "applicant_name",
        "date_of_birth",
        "email",
        "phone",
        "address",

        # Duplicate RC service references
        "registration_number",
        "chassis_number",
        "engine_number",
        "reason_for_duplicate",
        "mobile_number",
        "full_name",
        "state",
        "district",
        "grievance_description",
    }

    def __init__(self, values=None, approved_references=None):

        if values is None:
            values = {}

        if approved_references is None:
            approved_references = set()

        if not isinstance(values, dict):
            raise ValueError("Values must be a dictionary")

        if not isinstance(approved_references, (set, list, tuple)):
            raise ValueError("Approved references must be a collection")

        self._values = values.copy()
        self._approved_references = set(approved_references)

        if not self._approved_references.issubset(
            self.ALLOWED_REFERENCES
        ):
            raise ValueProviderError(
                "Unknown or forbidden value reference"
            )

        if not set(self._values).issubset(self.ALLOWED_REFERENCES):
            raise ValueProviderError(
                "Unsupported local value reference"
            )

    def is_approved(self, reference):
        """Check approval without exposing the actual private value."""
        return (
            isinstance(reference, str)
            and reference in self.ALLOWED_REFERENCES
            and reference in self._approved_references
            and reference in self._values
        )
    @classmethod
    def from_service_payload(cls, payload, approved_references=None):
        """
        Create a local value provider from an incoming service request.

        Approval must be supplied explicitly. Receiving service data
        does not automatically authorize filling form fields.
        """

        if not isinstance(payload, dict):
            raise ValueProviderError("Invalid service payload")

        form_payload = payload.get("form_payload")

        if not isinstance(form_payload, dict):
            raise ValueProviderError("Missing or invalid form_payload")

        if not set(form_payload).issubset(cls.ALLOWED_REFERENCES):
            raise ValueProviderError("Unsupported service form field")

        for key, value in form_payload.items():
            if not isinstance(value, str):
                raise ValueProviderError(
                    "Service form values must be strings"
                )

        return cls(
            values=form_payload,
            approved_references=approved_references or set(),
        )
        
    def resolve(self, reference):

        if not isinstance(reference, str):
            raise ValueProviderError("Reference must be a string")

        if reference not in self.ALLOWED_REFERENCES:
            raise ValueProviderError("Reference is not permitted")

        if reference not in self._approved_references:
            raise ValueProviderError(
                "User approval is required for this reference"
            )

        if reference not in self._values:
            raise ValueProviderError(
                "Requested local value is unavailable"
            )

        value = self._values[reference]

        if not isinstance(value, str) or not value.strip():
            raise ValueProviderError(
                "Local value must be a non-empty string"
            )

        return value