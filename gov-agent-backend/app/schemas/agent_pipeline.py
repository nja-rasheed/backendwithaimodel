from typing import List, Optional, Literal, Any
from pydantic import BaseModel, Field
from app.schemas.ai import ServiceIntentResponse
from app.schemas.eligibility import EligibilityCheckResponse


class ServiceIntentResult(BaseModel):
    service_category: str = Field(description="e.g. grievance, education, civic_infrastructure, social_welfare")
    service_name: str = Field(description="e.g. road_maintenance, higher_education_scholarship")
    user_type: str = Field(description="e.g. citizen, student, farmer")
    required_action: str = Field(description="e.g. file_complaint, check_eligibility, apply_for_subsidy")
    missing_information: List[str] = Field(default_factory=list)
    summary: str = Field(description="One-line summary")


class SchemeEligibilityRules(BaseModel):
    user_type: Optional[str] = Field(default="resident")
    state: Optional[str] = Field(default="All India")
    max_annual_family_income: Optional[float] = Field(default=None)
    education_level: Optional[str] = Field(default=None)


class DiscoveredSchemeItem(BaseModel):
    service_code: str
    name: str
    category: Literal[
        "education",
        "transport",
        "social_welfare",
        "civic_service",
        "agriculture",
        "employment",
        "healthcare"
    ]
    governance_tier: Literal["local", "state", "national", "hybrid"] = Field(
        default="state",
        description="'local' for municipal/roads, 'state' for state schemes, 'national' for pan-India, 'hybrid' for multi-tier schemes like scholarships"
    )
    portal_url: str
    description: str
    eligibility_criteria: SchemeEligibilityRules
    required_documents: List[str] = Field(default_factory=list)
    required_form_fields: List[str] = Field(
        default_factory=list,
        description="Key form fields required on the application/grievance form, e.g. ['full_name', 'landmark', 'rto_office']"
    )
    capabilities: List[str] = Field(
        default_factory=lambda: ["online_form"],
        description="Supported portal capabilities: 'online_form', 'document_upload', 'fee_payment', 'status_tracking', 'grievance_filing', or 'information_only'"
    )
    official_source: str = Field(default="Official Government Authority")


class DiscoveryResultContainer(BaseModel):
    schemes: List[DiscoveredSchemeItem] = Field(default_factory=list)


# Unified scheme structure delivered to the frontend
class EvaluatedSchemeItem(BaseModel):
    id: int
    service_code: str
    name: str
    category: str
    portal_url: str
    description: str
    eligibility: EligibilityCheckResponse
    capabilities: List[str] = Field(default_factory=list)


class AutonomousAgentAssistanceResponse(BaseModel):
    query: str
    citizen_state: str
    understood_intent: ServiceIntentResponse
    matched_schemes: List[EvaluatedSchemeItem]