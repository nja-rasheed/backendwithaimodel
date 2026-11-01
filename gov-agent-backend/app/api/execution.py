
import json
import logging
import re
from datetime import date
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth_utils import get_current_user
from app.models.user import User
from app.models.profile import CitizenProfile
from app.models.service import GovernmentService
from app.models.document import CitizenDocument
from app.services.supabase_storage import supabase_storage
from app.services.document_verifier import semantic_verifier

logger = logging.getLogger("agent.execution")
router = APIRouter(prefix="/api/execution", tags=["Bureaucracy Execution Engine"])


class ExecutionDraftRequest(BaseModel):
    service_id: int = Field(description="Database ID of the target GovernmentService")
    citizen_query: Optional[str] = Field(
        default="",
        description="Optional grievance/complaint text if filing a narrative request"
    )
    additional_fields: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Transaction-specific fields (e.g., license_number, chassis_number, landmark)"
    )


class MatchedAttachment(BaseModel):
    requirement: str
    filename: str
    download_url: str


class ExecutionManifestResponse(BaseModel):
    service_id: int
    service_name: str
    service_code: str
    portal_url: str
    governance_tier: str
    ready_for_dispatch: bool
    missing_form_fields: List[str] = Field(default_factory=list)
    missing_documents: List[str] = Field(default_factory=list)
    form_payload: Dict[str, Any] = Field(default_factory=dict)
    file_attachments: List[MatchedAttachment] = Field(default_factory=list)


def _infer_fallback_fields(service_name: str, category: str) -> List[str]:
    """Infers baseline mandatory fields if the database record has empty required_form_fields."""

    combined = f"{service_name} {category}".lower()

    if any(k in combined for k in ["rc", "registration certificate", "vehicle"]):
        return ["registration_number", "chassis_number", "engine_number", "reason_for_duplicate", "mobile_number"]

    elif any(k in combined for k in ["driving license", "dl", "licence"]):
        return ["driving_license_number", "date_of_birth", "rto_office"]

    elif any(k in combined for k in ["scholarship", "nsp", "student"]):
        return ["bank_account_number", "bank_ifsc", "institution_code"]

    elif any(k in combined for k in ["road", "pothole", "street light", "garbage", "drainage"]):
        return ["exact_location", "landmark"]

    return ["applicant_name", "contact_number"]


def _calculate_age(profile: Optional[CitizenProfile]) -> Optional[int]:
    """Calculate current age from DOB, falling back to stored age."""

    if not profile:
        return None

    if profile.dob:
        try:
            dob = date.fromisoformat(str(profile.dob).strip())
            today = date.today()

            age = today.year - dob.year

            if (today.month, today.day) < (dob.month, dob.day):
                age -= 1

            return age

        except (ValueError, TypeError):
            logger.warning("[ExecutionDraft] Invalid DOB format in citizen profile.")

    return profile.age


@router.post(
    "/draft",
    response_model=ExecutionManifestResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Pre-Validated Execution Manifest for Playwright"
)
async def generate_execution_draft(
    request: ExecutionDraftRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Fetch Target Government Service
    service = db.query(GovernmentService).filter(
        GovernmentService.id == request.service_id
    ).first()

    if not service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Government service with ID {request.service_id} not found."
        )

    # 2. Fetch User Profile & Document Vault
    profile = db.query(CitizenProfile).filter(
        CitizenProfile.user_id == current_user.id
    ).first()

    user_docs = db.query(CitizenDocument).filter(
        CitizenDocument.user_id == current_user.id
    ).all()

    # 3. Parse Stored Requirements
    raw_docs = getattr(service, "required_documents", "[]")
    required_docs: List[str] = (
        json.loads(raw_docs) if isinstance(raw_docs, str) else (raw_docs or [])
    )

    raw_fields = getattr(service, "required_form_fields", "[]")
    required_fields: List[str] = (
        json.loads(raw_fields) if isinstance(raw_fields, str) else (raw_fields or [])
    )

    if not required_fields:
        required_fields = _infer_fallback_fields(service.name, service.category)

    # 4. Semantic Document Verification & Signed URL Generation
    missing_docs: List[str] = []
    matched_attachments: List[MatchedAttachment] = []

    if required_docs:
        try:
            verification_result = await semantic_verifier.match_readiness(
                required_docs=required_docs,
                uploaded_docs=user_docs
            )
        except Exception as e:
            logger.error(f"[ExecutionDraft] Semantic verifier failed: {str(e)}")
            verification_result = None

        if verification_result and verification_result.matches:
            for match in verification_result.matches:
                if match.matched_uploaded_id:
                    doc_obj = next(
                        (d for d in user_docs if d.id == match.matched_uploaded_id),
                        None
                    )

                    if doc_obj:
                        signed_url = supabase_storage.get_signed_url(
                            doc_obj.storage_path, 3600
                        )

                        matched_attachments.append(
                            MatchedAttachment(
                                requirement=match.required_document,
                                filename=doc_obj.original_filename,
                                download_url=signed_url or ""
                            )
                        )
                else:
                    missing_docs.append(match.required_document)

        else:
            missing_docs = list(required_docs)

    # 5. Build Combined Pool with All Baseline Profile Attributes
    dob_val = str(profile.dob).strip() if (profile and profile.dob) else ""
    phone_val = str(profile.phone_number).strip() if (profile and profile.phone_number) else ""
    age_val = _calculate_age(profile)
    income_val = (
        str(profile.annual_family_income)
        if (profile and profile.annual_family_income is not None)
        else ""
    )
    edu_val = (
        profile.education_level
        if (profile and profile.education_level)
        else ""
    )

    combined_pool: Dict[str, Any] = {
        "full_name": (
            profile.full_name
            if profile and profile.full_name
            else ""
        ),
        "email": current_user.email,
        "dob": dob_val,
        "date_of_birth": dob_val,
        "birth_date": dob_val,
        "age": age_val if age_val is not None else "",
        "applicant_age": age_val if age_val is not None else "",
        "gender": profile.gender if (profile and profile.gender) else "",
        "applicant_gender": profile.gender if (profile and profile.gender) else "",
        "state": profile.state if (profile and profile.state) else "Tamil Nadu",
        "district": profile.district if (profile and profile.district) else "Tiruchirappalli",
        "phone_number": phone_val,
        "mobile_number": phone_val,
        "annual_family_income": income_val,
        "family_income": income_val,
        "annual_income": income_val,
        "income": income_val,
        "occupation_type": profile.occupation_type if profile else "student",
    }

    if profile:
        occ = (profile.occupation_type or "").lower()

        if occ == "student":
            combined_pool["education_level"] = edu_val
            combined_pool["educational_qualification"] = edu_val
            combined_pool["qualification"] = edu_val
            combined_pool["current_education"] = edu_val
            combined_pool["institution_name"] = profile.institution_name or ""
            combined_pool["college_name"] = profile.institution_name or ""
            combined_pool["school_name"] = profile.institution_name or ""
            combined_pool["course_or_degree"] = profile.course_or_degree or ""

        elif occ == "worker":
            combined_pool["employment_type"] = profile.employment_type or ""
            combined_pool["industry_or_sector"] = profile.industry_or_sector or ""
            combined_pool["employer_name"] = profile.employer_name or ""
            combined_pool["company_name"] = profile.employer_name or ""

    if request.citizen_query:
        combined_pool["grievance_description"] = request.citizen_query

    # Merge dynamic additional fields provided by frontend
    if request.additional_fields:
        for k, v in request.additional_fields.items():
            if v is not None and str(v).strip() != "":
                normalized_key = re.sub(r"[^a-z0-9]", "", k.lower())
                combined_pool[normalized_key] = v

    # 6. Validate Required Form Fields Against Combined Pool with Semantic Aliasing
    missing_fields: List[str] = []
    final_form_payload: Dict[str, Any] = {}
    pool_normalized = {
        re.sub(r"[^a-z0-9]", "", key.lower()): value
        for key, value in combined_pool.items()
    }

    income_val = next(
        (
            value for key, value in pool_normalized.items()
            if key in {"annualfamilyincome", "familyincome", "annualincome", "income"}
            and value is not None
            and str(value).strip() != ""
        ),
        ""
    )
    edu_val = next(
        (
            value for key, value in pool_normalized.items()
            if key in {
                "educationlevel",
                "educationalqualification",
                "qualification",
                "currenteducation"
            }
            and value is not None
            and str(value).strip() != ""
        ),
        ""
    )

    for field_name in required_fields:
        norm_key = re.sub(r"[^a-z0-9]", "", field_name.lower())
        value = pool_normalized.get(norm_key)

        # Synonym resolving
        if not value:
            if "income" in norm_key or "familyincome" in norm_key:
                value = income_val
            elif (
                "education" in norm_key
                or "qualification" in norm_key
                or "academic" in norm_key
            ):
                value = edu_val

            # Name synonyms
            elif norm_key in ["name", "applicantname", "candidatename", "ownername", "citizenname"]:
                value = combined_pool.get("full_name")

            # Date of Birth synonyms
            elif norm_key in ["dob", "dateofbirth", "birthdate", "applicantdob"]:
                value = combined_pool.get("dob") or combined_pool.get("date_of_birth")

            # Age synonyms
            elif norm_key in ["applicantage", "ageyears", "candidateage"]:
                value = combined_pool.get("age")

            # Gender synonyms
            elif norm_key in ["applicantgender", "sex", "applicantsex"]:
                value = combined_pool.get("gender")

            # Phone / Mobile synonyms
            elif norm_key in ["contactnumber", "phone", "mobile", "mobileno", "cellnumber", "phoneno"]:
                value = combined_pool.get("phone_number") or combined_pool.get("mobile_number")

            # Query / Description synonyms
            elif norm_key in ["complaint", "description", "details", "reason", "grievance", "remarks"]:
                value = combined_pool.get("grievance_description")

            # Regional location synonyms
            elif norm_key in ["city", "town", "taluk"]:
                value = combined_pool.get("district")

            elif norm_key in ["statename"]:
                value = combined_pool.get("state")

            # Education synonyms
            elif norm_key in ["college", "institution", "school", "university"]:
                value = combined_pool.get("institution_name")

            elif norm_key in ["degree", "course"]:
                value = combined_pool.get("course_or_degree") or combined_pool.get("education_level")

            # Work synonyms
            elif norm_key in ["employer", "company", "organization"]:
                value = combined_pool.get("employer_name")

        if value is not None and str(value).strip() != "":
            final_form_payload[norm_key] = value
        else:
            missing_fields.append(field_name)

    # Retain all core identity & demographic attributes in final_form_payload
    core_keys = [
        "full_name",
        "email",
        "state",
        "district",
        "mobile_number",
        "phone_number",
        "date_of_birth",
        "age",
        "gender"
    ]

    for core_key in core_keys:
        if (
            core_key in combined_pool
            and core_key not in final_form_payload
            and combined_pool[core_key]
        ):
            final_form_payload[core_key] = combined_pool[core_key]

    if "grievance_description" in combined_pool and "grievance_description" not in final_form_payload:
        final_form_payload["grievance_description"] = combined_pool["grievance_description"]

    is_ready = (len(missing_docs) == 0 and len(missing_fields) == 0)

    return ExecutionManifestResponse(
        service_id=service.id,
        service_name=service.name,
        service_code=service.service_code,
        portal_url=service.portal_url,
        governance_tier=getattr(service, "governance_tier", "state") or "state",
        ready_for_dispatch=is_ready,
        missing_form_fields=missing_fields,
        missing_documents=missing_docs,
        form_payload=final_form_payload,
        file_attachments=matched_attachments
    )
