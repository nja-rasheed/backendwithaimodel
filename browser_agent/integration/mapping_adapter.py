"""Translate backend field names into approved local value references.

Privacy boundary:
- Citizen values remain in the local execution environment.
- Only supported fields are retrieved.
- Values are passed to LocalValueProvider, never to an LLM.
- Filling a field requires explicit approval.
"""

from browser_agent.execution.value_provider import (
    LocalValueProvider,
    ValueProviderError,
)


class MappingAdapterError(ValueError):
    """Raised when backend fields cannot be safely mapped."""


class MappingAdapter:
    FIELD_ALIASES = {
        "full_name": "full_name",
        "applicant_name": "applicant_name",
        "name": "applicant_name",
        "email": "email",
        "date_of_birth": "date_of_birth",
        "dob": "date_of_birth",
        "birth_date": "date_of_birth",
        "phone": "phone",
        "phone_number": "mobile_number",
        "mobile_number": "mobile_number",
        "address": "address",
        "registration_number": "registration_number",
        "chassis_number": "chassis_number",
        "engine_number": "engine_number",
        "reason_for_duplicate": "reason_for_duplicate",
        "state": "state",
        "district": "district",
        "grievance_description": "grievance_description",
    }

    def __init__(self):
        self.allowed_references = set(
            LocalValueProvider.ALLOWED_REFERENCES
        )

    def map_backend_fields(self, backend_values):
        """Map backend field names to local provider references."""

        if not isinstance(backend_values, dict):
            raise MappingAdapterError(
                "Backend values must be a dictionary"
            )

        mapped_values = {}
        unsupported_fields = []

        for backend_field, value in backend_values.items():
            if not isinstance(backend_field, str):
                raise MappingAdapterError(
                    "Backend field names must be strings"
                )

            local_reference = self.FIELD_ALIASES.get(backend_field)

            if local_reference is None:
                unsupported_fields.append(backend_field)
                continue

            if local_reference not in self.allowed_references:
                raise MappingAdapterError(
                    "Alias points to an unsupported local reference"
                )

            if local_reference in mapped_values:
                raise MappingAdapterError(
                    "Multiple backend fields map to the same local reference"
                )

            if not isinstance(value, str):
                raise MappingAdapterError(
                    "Backend values must be strings"
                )

            mapped_values[local_reference] = value

        return {
            "values": mapped_values,
            "unsupported_fields": sorted(unsupported_fields),
        }

    def create_value_provider(
        self,
        backend_values,
        approved_references=None,
    ):
        """Create a local provider from already retrieved values."""

        result = self.map_backend_fields(backend_values)

        approved = set(approved_references or set())

        invalid_approvals = approved - self.allowed_references

        if invalid_approvals:
            raise MappingAdapterError(
                "Approval contains unsupported local references"
            )

        try:
            provider = LocalValueProvider(
                values=result["values"],
                approved_references=approved,
            )
        except ValueProviderError as error:
            raise MappingAdapterError(
                "Could not create local value provider"
            ) from error

        return {
            "provider": provider,
            "unsupported_fields": result["unsupported_fields"],
            "supported_references": sorted(result["values"]),
        }

    def create_value_provider_from_service_request(
        self,
        service_request_adapter,
        safe_request,
        approved_references=None,
    ):
        """Build a provider using values stored locally.

        Original backend field names are used to retrieve values.
        Aliases identify the corresponding local provider references.

        No citizen values are included in an LLM task or prompt.
        """

        if not isinstance(safe_request, dict):
            raise MappingAdapterError(
                "Invalid safe service request"
            )

        if not callable(
            getattr(service_request_adapter, "get_local_value", None)
        ):
            raise MappingAdapterError(
                "Invalid service request adapter"
            )

        field_names = safe_request.get("form_field_names")

        if not isinstance(field_names, list):
            raise MappingAdapterError(
                "Invalid service request field names"
            )

        backend_values = {}
        unsupported_fields = []
        seen_references = set()

        for field_name in field_names:
            if (
                not isinstance(field_name, str)
                or not field_name.strip()
            ):
                raise MappingAdapterError(
                    "Backend field names must be non-empty strings"
                )

            local_reference = self.FIELD_ALIASES.get(field_name)

            if local_reference is None:
                unsupported_fields.append(field_name)
                continue

            if local_reference not in self.allowed_references:
                raise MappingAdapterError(
                    "Alias points to an unsupported local reference"
                )

            # Avoid duplicate aliases mapping to the same reference.
            # Example: "name" and "applicant_name".
            if local_reference in seen_references:
                continue

            # Mark this reference before retrieving its value.
            seen_references.add(local_reference)

            try:
                value = service_request_adapter.get_local_value(
                    field_name
                )
            except Exception as error:
                raise MappingAdapterError(
                    "Could not retrieve a local service value"
                ) from error

            # Normalize basic scalar values locally.
            if value is None:
                value = ""
            elif isinstance(value, (int, float, bool)):
                value = str(value)
            elif not isinstance(value, str):
                raise MappingAdapterError(
                    "Local service value has an unsupported type"
                )

            backend_values[field_name] = value

        result = self.create_value_provider(
            backend_values,
            approved_references=approved_references,
        )

        result["unsupported_fields"] = sorted(
            set(
                result["unsupported_fields"] + unsupported_fields
            )
        )

        return result