
import json
import logging
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel
from app.models.profile import CitizenProfile
from app.models.service import GovernmentService
from app.schemas.eligibility import EligibilityCheckResponse, CriterionEvaluation
from app.services.gemini_base import gemini_fast_client

logger = logging.getLogger("agent.eligibility")


def normalize_text(val: Optional[str]) -> str:
    if not val:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(val).lower().strip())


def _parse_numeric_value(val: object) -> Optional[float]:
    numeric_match = re.search(
        r"-?\d+(?:\.\d+)?",
        str(val).replace(",", "")
    )
    return float(numeric_match.group()) if numeric_match else None


class SemanticEquivalenceSchema(BaseModel):
    is_equivalent_or_satisfies: bool
    reason: str


async def check_semantic_education_match(required: str, actual: str) -> bool:
    if not required or not actual:
        return False

    prompt = f"""
Compare these two educational qualifications in the context of government schemes:
- Requirement: "{required}"
- Applicant Qualification: "{actual}"

Does the applicant's qualification satisfy or match the requirement?
Account for abbreviations, equivalent degrees, qualification tiers, regional terminology,
and standard educational ladders. Return true only when the applicant meets or matches
the requirement, otherwise return false.
"""
    result: Optional[SemanticEquivalenceSchema] = (
        await gemini_fast_client.execute_structured_query(
            task_name="EducationSemanticEquivalence",
            prompt=prompt,
            system_instruction=(
                "You are an educational qualification equivalency engine for public "
                "services. Evaluate qualification equivalence accurately."
            ),
            schema=SemanticEquivalenceSchema
        )
    )
    return bool(result and result.is_equivalent_or_satisfies)


@lru_cache(maxsize=256)
def _cached_semantic_education_match(required: str, actual: str) -> bool:
    coroutine = check_semantic_education_match(required, actual)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


class EligibilityService:

    @staticmethod
    def _calculate_age(profile: CitizenProfile) -> Optional[int]:
        """
        Calculate age using DOB.
        Falls back to the stored age if DOB is unavailable or invalid.
        """

        if profile.dob:
            try:
                dob = date.fromisoformat(str(profile.dob).strip())
                today = date.today()

                age = today.year - dob.year

                if (today.month, today.day) < (dob.month, dob.day):
                    age -= 1

                return age

            except (ValueError, TypeError):
                logger.warning("Invalid DOB format in citizen profile.")

        return profile.age

    @staticmethod
    def evaluate(
        profile: Optional[CitizenProfile],
        service: GovernmentService
    ) -> EligibilityCheckResponse:

        # Load rules & documents from stored JSON
        rules = (
            json.loads(service.eligibility_rules)
            if isinstance(service.eligibility_rules, str)
            else (service.eligibility_rules or {})
        )

        docs = (
            json.loads(service.required_documents)
            if isinstance(service.required_documents, str)
            else (service.required_documents or [])
        )

        breakdown: List[CriterionEvaluation] = []
        missing_data: List[str] = []
        overall_eligible = True

        # If user has no profile filled out yet
        if not profile:
            return EligibilityCheckResponse(
                service_id=service.id,
                service_name=service.name,
                service_code=service.service_code,
                is_eligible=False,
                evaluation_breakdown=[],
                required_documents_to_prepare=docs,
                missing_profile_data=["citizen_profile_not_found"],
                next_action_instructions="Complete your citizen profile to verify eligibility."
            )

        # 1. State / Residency Verification
        req_state = rules.get("state")

        if req_state and req_state.lower() not in ["all india", "national", "central"]:
            actual_state = profile.state or "Unknown"

            passed = actual_state.strip().lower() == req_state.strip().lower()

            if not passed:
                overall_eligible = False

            breakdown.append(CriterionEvaluation(
                criterion="State / Jurisdiction Residency",
                required=req_state,
                actual=actual_state,
                passed=passed,
                remarks="Resident jurisdiction matches." if passed else f"Only valid for residents of {req_state}."
            ))

        # 2. Target Beneficiary / Occupation Verification
        target_role = rules.get("target_role") or rules.get("occupation")

        if target_role:
            actual_role = profile.occupation_type or ""

            norm_target = normalize_text(target_role)
            norm_user_occ = normalize_text(actual_role)
            passed = (
                norm_target in norm_user_occ
                or norm_user_occ in norm_target
            )

            if not passed:
                overall_eligible = False

            breakdown.append(CriterionEvaluation(
                criterion="Target Beneficiary Role",
                required=target_role.title(),
                actual=actual_role.title(),
                passed=passed,
                remarks=f"Beneficiary role matches ({target_role})." if passed else f"This service is strictly for {target_role}s."
            ))

        # 3. Income Ceiling Verification
        max_income = (
            rules.get("max_annual_family_income")
            if rules.get("max_annual_family_income") is not None
            else rules.get("income_ceiling")
            if rules.get("income_ceiling") is not None
            else rules.get("annual_family_income")
            if rules.get("annual_family_income") is not None
            else rules.get("max_income")
        )

        if max_income is not None:
            actual_income = profile.annual_family_income

            if actual_income is None:
                missing_data.append("annual_family_income")
                overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Annual Family Income Ceiling",
                    required=f"<= Rs. {max_income}",
                    actual="Not provided in profile",
                    passed=False,
                    remarks="Income detail missing from profile."
                ))

            else:
                required_income = _parse_numeric_value(max_income)
                profile_income = _parse_numeric_value(actual_income)

                passed = (
                    required_income is not None
                    and profile_income is not None
                    and profile_income <= required_income
                )

                if not passed:
                    overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Annual Family Income Ceiling",
                    required=f"<= Rs. {max_income}",
                    actual=f"Rs. {actual_income}",
                    passed=passed,
                    remarks="Income is within the permissible limit." if passed else "Annual income exceeds the permissible limit."
                ))

        # 4. Educational Qualification Check
        req_edu = (
            rules.get("education_level")
            or rules.get("educational_qualification")
            or rules.get("qualification")
        )

        if req_edu:
            is_student = (profile.occupation_type or "").lower() == "student"
            actual_edu = profile.education_level or ""

            if is_student and not actual_edu:
                missing_data.append("education_level")
                overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Educational Qualification",
                    required=req_edu,
                    actual="Missing in profile",
                    passed=False,
                    remarks="Student profile must include education level."
                ))

            elif actual_edu:
                norm_req = normalize_text(req_edu)
                norm_actual = normalize_text(actual_edu)
                passed = (
                    norm_req in norm_actual
                    or norm_actual in norm_req
                )
                if not passed:
                    passed = _cached_semantic_education_match(
                        req_edu,
                        actual_edu
                    )

                if not passed:
                    overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Educational Qualification",
                    required=req_edu,
                    actual=actual_edu,
                    passed=passed,
                    remarks="Educational criteria satisfied." if passed else f"Requires {req_edu} qualification."
                ))

            else:
                breakdown.append(CriterionEvaluation(
                    criterion="Educational Qualification",
                    required=req_edu,
                    actual="Non-student profile (N/A)",
                    passed=True,
                    remarks="Educational qualification waived for non-student occupation."
                ))

        # 5. Worker Employment Verification
        req_emp_type = rules.get("employment_type")

        if req_emp_type:
            actual_emp_type = profile.employment_type or ""

            if not actual_emp_type:
                missing_data.append("employment_type")
                overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Employment Classification",
                    required=req_emp_type,
                    actual="Missing in profile",
                    passed=False,
                    remarks="Worker profile must include employment classification."
                ))

            else:
                passed = req_emp_type.lower() in actual_emp_type.lower()

                if not passed:
                    overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Employment Classification",
                    required=req_emp_type,
                    actual=actual_emp_type,
                    passed=passed,
                    remarks="Employment type matches." if passed else f"Requires {req_emp_type} status."
                ))

        # 6. Minimum and Maximum Age Verification
        min_age = rules.get("min_age")
        max_age = rules.get("max_age")

        if min_age is not None or max_age is not None:

            actual_age = EligibilityService._calculate_age(profile)

            required_age = (
                f"{min_age if min_age is not None else 0}"
                f" - "
                f"{max_age if max_age is not None else 'No upper limit'} years"
            )

            if actual_age is None:
                missing_data.append("age")
                overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Age Eligibility",
                    required=required_age,
                    actual="Age not provided",
                    passed=False,
                    remarks="Date of birth or age is required to verify eligibility."
                ))

            else:
                passed = True

                if min_age is not None and actual_age < int(min_age):
                    passed = False

                if max_age is not None and actual_age > int(max_age):
                    passed = False

                if not passed:
                    overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Age Eligibility",
                    required=required_age,
                    actual=f"{actual_age} years",
                    passed=passed,
                    remarks=(
                        "Age requirement satisfied."
                        if passed
                        else f"Applicant must satisfy the age requirement of {required_age}."
                    )
                ))

        # 7. Gender Eligibility Verification
        req_gender = rules.get("gender")

        if req_gender and req_gender.lower() not in ["all", "any"]:
            actual_gender = (profile.gender or "").strip().lower()

            if not actual_gender:
                missing_data.append("gender")
                overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Gender Eligibility",
                    required=req_gender.title(),
                    actual="Not provided",
                    passed=False,
                    remarks="Gender information is required to verify eligibility."
                ))

            else:
                passed = actual_gender == req_gender.strip().lower()

                if not passed:
                    overall_eligible = False

                breakdown.append(CriterionEvaluation(
                    criterion="Gender Eligibility",
                    required=req_gender.title(),
                    actual=actual_gender.title(),
                    passed=passed,
                    remarks=(
                        "Gender requirement satisfied."
                        if passed
                        else f"This scheme is applicable to {req_gender} applicants."
                    )
                ))

        # 8. Universal Access Fallback
        if not breakdown:
            breakdown.append(CriterionEvaluation(
                criterion="Public Service Access",
                required="Open to all citizens",
                actual="Citizen",
                passed=True,
                remarks="Universal access service. No demographic or occupational restrictions."
            ))

        # Action instructions
        if overall_eligible:
            instructions = f"You are eligible. Prepare the required documents and proceed to {service.portal_url} to apply."
        else:
            instructions = "You do not satisfy one or more criteria for this scheme. Review the breakdown."

        return EligibilityCheckResponse(
            service_id=service.id,
            service_name=service.name,
            service_code=service.service_code,
            is_eligible=overall_eligible,
            evaluation_breakdown=breakdown,
            required_documents_to_prepare=docs,
            missing_profile_data=missing_data,
            next_action_instructions=instructions
        )


eligibility_service = EligibilityService()
