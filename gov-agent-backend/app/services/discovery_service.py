import logging
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
from app.schemas.agent_pipeline import (
    DiscoveredSchemeItem,
    DiscoveryResultContainer
)
from app.services.gemini_base import gemini_fast_client

logger = logging.getLogger("agent.pipeline")

OFFICIAL_AUTHORITY_DOMAINS = [
    "gov.in",
    "nic.in",
    "parivahan.gov.in",
    "tnega.org",
    "myscheme.in",
    "tnebnet.org",
    "tnpdcl.org",
    "tnebltd.gov.in",
    "chennaicorporation.gov.in",
    "gccservices.in",
    "twadboard.tn.gov.in"
]

PRIMARY_DISCOVERY_PROMPT = """
You are an autonomous Government Scheme & Official Portal Discovery Engine for India.
Analyze the citizen's query, category, specific intent, and regional/demographic context.

CANONICAL CATEGORY RULES:
1. Set each scheme's category to exactly one of:
   ['education', 'transport', 'social_welfare', 'civic_service', 'agriculture', 'employment', 'healthcare'].
2. Classify by primary function. Scholarships, student fellowships, educational grants,
   and student financial portals are always 'education'.
3. Road, municipal, garbage, streetlight, and civic complaints are 'civic_service'.
4. Driving licences, LLR, vehicle RC, and transport services are 'transport'.
5. Pensions, disability aid, and ration cards are 'social_welfare'.

CRITICAL PORTAL CAPABILITY RULES:
1. Identify direct interactive portals where citizens submit forms or complaints online.
2. Tag each portal with accurate capabilities selected from:
   ['online_form', 'document_upload', 'fee_payment', 'status_tracking', 'grievance_filing', 'information_only'].
3. If a portal is purely a static guide, circular, or departmental overview without online forms, tag it strictly with ['information_only'].
4. Prefer portals that support the citizen's requested transaction over informational directories.

JURISDICTION & GOVERNANCE TIER:
   - 'local': Municipal issues, road/drainage damage, streetlights, garbage, water supply. Anchor to citizen's district/city and state.
   - 'state': State-specific welfare, land records (Patta/Chitta), state electricity boards.
   - 'national': Central schemes and ministries.
   - 'hybrid': Issues with both central and state programs (e.g., scholarships). Return 1 Central portal (All India) AND 1 State-specific scheme.
DEMOGRAPHIC TARGETING:
   - Match eligibility using the provided citizen demographic context (age, gender, education, occupation).
   - Do NOT propose schemes whose age or gender criteria conflict with the provided demographic context.
Extract clean 'required_documents' and essential 'required_form_fields'.
Descriptions must be brief (under 25 words).
"""

AUTONOMOUS_RECOVERY_PROMPT = """
You are an expert Government Redressal & Public Administration Architect.
A previous automated lookup did not return a usable result.

Your task is to identify the single most authoritative government authority, apex portal, or nodal department that formally addresses this citizen issue.

CONSTRAINTS:
1. Select the most authoritative portal for the requested action.
2. Identify whether the portal supports online forms, document uploads, fee payment, status tracking, or grievance filing.
3. Use ['information_only'] only for a portal without an interactive submission workflow.
4. Generate realistic, minimal required documents, required form fields, and structured eligibility rules.
"""

def calculate_capability_rank(capabilities: List[str]) -> int:
    caps = set(c.lower() for c in (capabilities or []))
    if "online_form" in caps and "document_upload" in caps:
        return 0
    if "online_form" in caps or "grievance_filing" in caps:
        return 1
    if "information_only" in caps:
        return 3
    return 2


class SchemeDiscoveryService:
    @staticmethod
    def _is_official_url(url: str) -> bool:
        try:
            hostname = (urlparse(url).hostname or "").lower()
            return any(
                hostname == domain or hostname.endswith(f".{domain}")
                for domain in OFFICIAL_AUTHORITY_DOMAINS
            )
        except ValueError:
            return False

    async def _autonomous_fallback_synthesis(
        self,
        service_category: str,
        service_name: str,
        citizen_query: str,
        user_state: str,
        user_district: str,
        demographics: Optional[Dict[str, Any]] = None
    ) -> List[DiscoveredSchemeItem]:
        """
        Dynamically derives the authoritative nodal department
        without hardcoded keyword rules.
        """
        logger.info("[SchemeDiscovery] Executing autonomous fallback synthesis...")

        demo_str = ""
        if demographics:
            demo_parts = [f"- {k.replace('_', ' ').title()}: {v}" for k, v in demographics.items() if v]
            if demo_parts:
                demo_str = "\nCitizen Demographic Context (Non-PII):\n" + "\n".join(demo_parts)

        prompt = f"""
Identify the apex official Indian government authority/portal for this issue:
- Issue Category: {service_category}
- Specific Action/Service: {service_name}
- Citizen Query: {citizen_query}
- State Jurisdiction: {user_state}
- District/City: {user_district}
{demo_str}

Return exactly 1 high-priority, strictly verified government service or portal.
"""

        result: DiscoveryResultContainer = await gemini_fast_client.execute_structured_query(
            task_name="AutonomousRecovery",
            prompt=prompt,
            system_instruction=AUTONOMOUS_RECOVERY_PROMPT,
            schema=DiscoveryResultContainer
        )

        if not result or not result.schemes:
            return []

        return [
            scheme for scheme in result.schemes
            if self._is_official_url(scheme.portal_url)
        ]

    async def discover_schemes(
        self,
        service_category: str,
        service_name: str,
        citizen_query: str,
        user_state: Optional[str] = "Tamil Nadu",
        user_district: Optional[str] = "Tiruchirappalli",
        demographics: Optional[Dict[str, Any]] = None
    ) -> List[DiscoveredSchemeItem]:
        effective_state = user_state or "Tamil Nadu"
        effective_district = user_district or "Tiruchirappalli"

        demo_str = ""
        if demographics:
            demo_parts = [f"- {k.replace('_', ' ').title()}: {v}" for k, v in demographics.items() if v]
            if demo_parts:
                demo_str = "\nCitizen Demographic Context (Non-PII):\n" + "\n".join(demo_parts)

        prompt = f"""
Find authentic government portals, departments, or schemes for:
- Citizen Query: {citizen_query}
- Service Category: {service_category}
- Specific Intent: {service_name}
- Citizen State Jurisdiction: {effective_state}
- Citizen District/City: {effective_district}
{demo_str}

INSTRUCTIONS:
1. Return portals that directly support the requested citizen action when available, and accurately populate each portal's capabilities.
2. If a portal is informational only, set capabilities to ['information_only'].
3. Civic Issues: If relating to roads, drainage, garbage, or civic infrastructure, anchor to municipal/district authorities for {effective_district}, {effective_state} (governance_tier: 'local').
4. Scholarships: Return up to 2 options: One authoritative Central portal (governance_tier: 'national') AND one State-level scheme for {effective_state} (governance_tier: 'state').
5. Demographics: Use the non-PII demographic attributes (age, gender, education, occupation) to narrow down eligibility criteria.
6. Extract both 'required_documents' and 'required_form_fields' for each discovered service.
"""

        result: DiscoveryResultContainer = await gemini_fast_client.execute_structured_query(
            task_name="SchemeDiscovery",
            prompt=prompt,
            system_instruction=PRIMARY_DISCOVERY_PROMPT,
            schema=DiscoveryResultContainer
        )

        valid_schemes: List[DiscoveredSchemeItem] = []

        if result and result.schemes:
            for scheme in result.schemes:
                if self._is_official_url(scheme.portal_url):
                    valid_schemes.append(scheme)
                else:
                    logger.warning(
                        f"[SchemeDiscovery] Rejected non-official URL: {scheme.portal_url}"
                    )

        if valid_schemes:
            valid_schemes.sort(key=lambda s: calculate_capability_rank(s.capabilities))
            return valid_schemes

        # If primary discovery yields no schemes, run the autonomous synthesis.
        fallback_schemes = await self._autonomous_fallback_synthesis(
            service_category=service_category,
            service_name=service_name,
            citizen_query=citizen_query,
            user_state=effective_state,
            user_district=effective_district,
            demographics=demographics
        )
        fallback_schemes.sort(key=lambda s: calculate_capability_rank(s.capabilities))
        return fallback_schemes


discovery_service = SchemeDiscoveryService()