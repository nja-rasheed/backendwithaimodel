from enum import Enum


class VerificationStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNCERTAIN = "uncertain"


class VerificationError(Exception):
    pass


class ActionVerifier:
    """
    Verifies browser actions using before-and-after observations.

    Does not assume that successful Playwright execution
    means the intended result occurred.
    """

    def verify_click(
        self,
        before_observation,
        after_observation,
        target,
        execution_result,
    ):
        if not isinstance(before_observation, dict):
            raise VerificationError("Invalid before observation")

        if not isinstance(after_observation, dict):
            raise VerificationError("Invalid after observation")

        if not isinstance(target, str) or not target.strip():
            raise VerificationError("Invalid click target")

        if not isinstance(execution_result, dict):
            raise VerificationError("Invalid execution result")

        if execution_result.get("status") != "executed":
            return {
                "status": VerificationStatus.FAILURE.value,
                "reason": "Click execution was not successful",
            }

        # Compare observable page structure.
        before = {
            "title": before_observation.get("title"),
            "headings": before_observation.get("headings", []),
            "buttons": before_observation.get("buttons", []),
            "links": before_observation.get("links", []),
            "input_fields": before_observation.get("input_fields", []),
        }

        after = {
            "title": after_observation.get("title"),
            "headings": after_observation.get("headings", []),
            "buttons": after_observation.get("buttons", []),
            "links": after_observation.get("links", []),
            "input_fields": after_observation.get("input_fields", []),
        }

        if before != after:
            return {
                "status": VerificationStatus.SUCCESS.value,
                "reason": "Browser structure changed after the click",
            }

        return {
            "status": VerificationStatus.UNCERTAIN.value,
            "reason": "No observable structural change detected",
        }