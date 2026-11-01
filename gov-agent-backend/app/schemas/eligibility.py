from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class CriterionEvaluation(BaseModel):
    criterion: str
    required: Any
    actual: Any
    passed: bool
    remarks: str


class EligibilityCheckResponse(BaseModel):
    service_id: int
    service_name: str
    service_code: str
    is_eligible: bool
    evaluation_breakdown: List[CriterionEvaluation]
    required_documents_to_prepare: List[str]
    missing_profile_data: List[str]
    next_action_instructions: str