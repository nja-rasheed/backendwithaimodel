import logging
from app.schemas.ai import ServiceIntentResponse
from app.schemas.agent_pipeline import ServiceIntentResult
from app.services.gemini_base import gemini_fast_client

logger = logging.getLogger("agent.pipeline")

INTENT_SYSTEM_PROMPT = """
You are an expert Government Bureaucracy and Public Service AI Intent Classifier.
Analyze the citizen's query and extract their true public service intent.

RULES:
1. Accurately assign service_category (e.g. grievance, education, civic_infrastructure, social_welfare, agriculture, disaster_management).
2. Determine specific service_name (e.g. flood_relief_subsidy, road_damage_complaint).
3. Identify citizen's user_type and missing_information.
4. Keep the summary concise and strictly factual.

CONVERSATIONAL & GREETING HANDLING:
- If the citizen's query is a greeting, casual check-in, polite pleasantry, or meta-question
  (e.g., "Hi", "How are you", "What can you do?"):
  1. Set service_category to "general".
  2. Set service_name to "general_inquiry".
  3. Set required_action to "respond_to_greeting".
  4. Set missing_information to [].
  5. Phrase summary as a direct, first-person, friendly reply to the citizen, not a
     third-person classification note. Acknowledge the message and ask how you can help
     with public schemes, scholarships, licensing, or grievances.
"""


class GeminiService:
    async def understand_request(self, query: str) -> ServiceIntentResponse:
        result: ServiceIntentResult = await gemini_fast_client.execute_structured_query(
            task_name="IntentExtraction",
            prompt=f"Classify this citizen request: '{query}'",
            system_instruction=INTENT_SYSTEM_PROMPT,
            schema=ServiceIntentResult
        )

        if result:
            return ServiceIntentResponse(
                service_category=result.service_category,
                service_name=result.service_name,
                user_type=result.user_type,
                required_action=result.required_action,
                missing_information=result.missing_information,
                summary=result.summary
            )

        # Dynamic fallback if all external models are unavailable
            # Dynamic fallback if all external models are unavailable
        q = query.lower()

        # Education and scholarships
        if any(word in q for word in [
            "scholarship", "undergraduate", "student",
            "college", "tuition", "education", "university",
            "engineering student", "financial assistance"
        ]):
            category = "education"
            service = "scholarship_assistance"
            user_type = "student"
            action = "find_schemes"
            missing = []

        # Agriculture
        elif any(word in q for word in [
            "farmer", "farming", "agriculture", "crop",
            "irrigation", "agricultural subsidy"
        ]):
            category = "agriculture"
            service = "agricultural_assistance"
            user_type = "citizen"
            action = "find_schemes"
            missing = []

        # Disaster relief
        elif any(word in q for word in [
            "flood", "disaster", "earthquake", "cyclone"
        ]):
            category = "disaster_management"
            service = "disaster_relief_assistance"
            user_type = "citizen"
            action = "find_schemes"
            missing = ["exact_location"]

        # Grievances
        elif any(word in q for word in [
            "complaint", "grievance", "report",
            "broken road", "road damage"
        ]):
            category = "grievance"
            service = "public_service_grievance"
            user_type = "citizen"
            action = "submit_grievance"
            missing = []

        # General fallback
        else:
            category = "general"
            service = "general_inquiry"
            user_type = "citizen"
            action = "clarify_request"
            missing = []

        return ServiceIntentResponse(
            service_category=category,
            service_name=service,
            user_type=user_type,
            required_action=action,
            missing_information=missing,
            summary=f"Identified {service.replace('_', ' ')} request: {query}"
        )


gemini_service = GeminiService()