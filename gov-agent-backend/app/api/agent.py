import json
import time
import logging
from typing import List, Dict, Any
from datetime import datetime
from sqlalchemy import func
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth_utils import get_current_user
from app.models.user import User
from app.models.profile import CitizenProfile
from app.models.service import GovernmentService, UserDiscoveredService
from app.services.gemini_service import gemini_service
from app.services.discovery_service import calculate_capability_rank, discovery_service
from app.services.eligibility_service import eligibility_service
from app.schemas.ai import AIUnderstandRequest
from app.schemas.agent_pipeline import (
    AutonomousAgentAssistanceResponse,
    EvaluatedSchemeItem
)

logger = logging.getLogger("agent.pipeline")
router = APIRouter(prefix="/api/agent", tags=["Autonomous Citizen Agent"])


@router.post(
    "/assist",
    response_model=AutonomousAgentAssistanceResponse,
    status_code=status.HTTP_200_OK,
    summary="One-Shot Autonomous Pipeline: Intent + Discovery + Auto-Eligibility"
)
async def autonomous_assist(
    payload: AIUnderstandRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    total_start = time.perf_counter()
    logger.info(f"===> [Pipeline Start] User ID: {current_user.id} | Query: '{payload.query}'")

    # 1. Resolve Profile, State, District & Non-PII Demographic Context
    profile = db.query(CitizenProfile).filter(CitizenProfile.user_id == current_user.id).first()
    state = profile.state if (profile and profile.state) else "Tamil Nadu"
    district = profile.district if (profile and profile.district) else "Tiruchirappalli"

    demographic_context: Dict[str, Any] = {}
    if profile:
        actual_age = getattr(profile, "age", None)
        if actual_age is None and getattr(profile, "dob", None):
            try:
                birth_year = datetime.strptime(str(profile.dob).strip()[:10], "%Y-%m-%d").year
                actual_age = datetime.now().year - birth_year
            except Exception:
                actual_age = None

        demographic_context = {
            "age": actual_age,
            "gender": getattr(profile, "gender", None),
            "occupation_type": getattr(profile, "occupation_type", "student"),
            "education_level": getattr(profile, "education_level", None),
            "employment_type": getattr(profile, "employment_type", None)
        }

    # 2. Understand intent before deciding whether discovery is actionable
    t_llm = time.perf_counter()
    intent = await gemini_service.understand_request(payload.query)
    logger.info(f"===> [Intent Task Finished] in {time.perf_counter() - t_llm:.2f}s")

    intent_values = {
        str(getattr(intent, "service_category", "")).strip().lower(),
        str(getattr(intent, "service_name", "")).strip().lower(),
        str(getattr(intent, "required_action", "")).strip().lower()
    }
    non_actionable_values = {
        "greeting",
        "conversational",
        "general_inquiry",
        "none",
        "greet",
        "general_service",
        "unknown"
    }
    if intent_values & non_actionable_values:
        return AutonomousAgentAssistanceResponse(
            query=payload.query,
            citizen_state=state,
            understood_intent=intent,
            matched_schemes=[]
        )

    discovered = await discovery_service.discover_schemes(
        service_category=intent.service_category,
        service_name=intent.service_name,
        citizen_query=payload.query,
        user_state=state,
        user_district=district,
        demographics=demographic_context
    )
    unique_discovered = []
    seen_scheme_keys = set()
    for item in discovered:
        scheme_key = item.service_code.strip().lower() or item.portal_url.strip().lower()
        if scheme_key and scheme_key not in seen_scheme_keys:
            seen_scheme_keys.add(scheme_key)
            unique_discovered.append(item)
    discovered = unique_discovered

    # 3. Batch DB Persistence & Instant Auto-Eligibility Evaluation
    t_eval = time.perf_counter()
    evaluated_schemes: List[EvaluatedSchemeItem] = []

    if discovered:
        # Fetch existing schemes to avoid duplicate records
        service_codes = [item.service_code for item in discovered]
        existing_records = {
            s.service_code: s for s in db.query(GovernmentService).filter(
                GovernmentService.service_code.in_(service_codes)
            ).all()
        }

        for item in discovered:
            rules_dict = item.eligibility_criteria.model_dump()
            service_record = existing_records.get(item.service_code)

            if not service_record:
                # Insert new service with both documents and form fields
                service_record = GovernmentService(
                    service_code=item.service_code,
                    name=item.name,
                    category=item.category,
                    governance_tier=getattr(item, "governance_tier", "state"),
                    portal_url=item.portal_url,
                    description=item.description,
                    eligibility_rules=json.dumps(rules_dict),
                    required_documents=json.dumps(item.required_documents),
                    required_form_fields=json.dumps(getattr(item, "required_form_fields", []))
                )
                db.add(service_record)
                db.flush()  # Populates service_record.id immediately
            else:
                # Update existing records if fields or governance tier need alignment
                updated = False
                if not getattr(service_record, "required_form_fields", None) or service_record.required_form_fields == "[]":
                    service_record.required_form_fields = json.dumps(getattr(item, "required_form_fields", []))
                    updated = True
                if not getattr(service_record, "governance_tier", None):
                    service_record.governance_tier = getattr(item, "governance_tier", "state")
                    updated = True
                if (
                    service_record.category == "civic_service"
                    and item.category != "civic_service"
                ):
                    service_record.category = item.category
                    updated = True
                if updated:
                    db.flush()

            existing_link = db.query(UserDiscoveredService).filter(
                UserDiscoveredService.user_id == current_user.id,
                UserDiscoveredService.service_id == service_record.id
            ).first()
            if not existing_link:
                db.add(UserDiscoveredService(
                    user_id=current_user.id,
                    service_id=service_record.id
                ))
            else:
                existing_link.discovered_at = func.now()

            # Deterministic Rule Evaluation against the citizen's profile
            eligibility_result = eligibility_service.evaluate(
                profile=profile,
                service=service_record
            )

            # Safely parse JSON strings for the response schema
            raw_docs = getattr(service_record, "required_documents", "[]")
            parsed_docs = json.loads(raw_docs) if isinstance(raw_docs, str) else (raw_docs or [])

            raw_fields = getattr(service_record, "required_form_fields", "[]")
            parsed_fields = json.loads(raw_fields) if isinstance(raw_fields, str) else (raw_fields or [])

            evaluated_schemes.append(
                EvaluatedSchemeItem(
                    id=service_record.id,
                    service_code=service_record.service_code,
                    name=service_record.name,
                    category=service_record.category,
                    governance_tier=getattr(service_record, "governance_tier", "state") or "state",
                    portal_url=service_record.portal_url,
                    description=service_record.description,
                    required_documents=parsed_docs,
                    required_form_fields=parsed_fields,
                    eligibility=eligibility_result,
                    capabilities=getattr(item, "capabilities", ["online_form"])
                )
            )

        db.commit()

        evaluated_schemes.sort(key=lambda s: calculate_capability_rank(s.capabilities))

    logger.info(f"===> [Persistence & Auto-Eligibility Completed] in {time.perf_counter() - t_eval:.3f}s")
    logger.info(f"===> [Total Pipeline Runtime] {time.perf_counter() - total_start:.2f}s")

    return AutonomousAgentAssistanceResponse(
        query=payload.query,
        citizen_state=state,
        understood_intent=intent,
        matched_schemes=evaluated_schemes
    )