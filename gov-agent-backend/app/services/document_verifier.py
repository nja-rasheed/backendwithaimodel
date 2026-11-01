import json
import logging
from typing import List
from app.models.document import CitizenDocument
from app.schemas.document import SemanticReadinessResult
from app.services.gemini_base import gemini_fast_client

logger = logging.getLogger("agent.documents")

DOCUMENT_MATCHER_PROMPT = """
You are an expert Indian Government Bureaucracy & Document Verification Specialist.
Your task is to semantically match a list of official required documents against a citizen's uploaded document vault.

RULES:
1. Match semantically, taking into account Indian administrative conventions:
   - "Aadhaar / Aadhar / UIDAI / UID" refer to the same identity document.
   - "Smart Ration Card / Family Card / TNEPDS" are equivalent.
   - "FIR / LDR / Police CSR" satisfy police reporting requirements.
   - "DL / Driving License" match driving credential proofs.
   - "Community Certificate / Caste Certificate" are equivalent.
2. Do NOT falsely match unrelated documents (e.g., an "Income Certificate" cannot satisfy an "Aadhaar Card" requirement).
3. If no uploaded document satisfies the requirement, set `matched_uploaded_id` and `matched_filename` to null.
"""


class DocumentSemanticVerifier:
    async def match_readiness(
        self,
        required_docs: List[str],
        uploaded_docs: List[CitizenDocument]
    ) -> SemanticReadinessResult:
        if not required_docs:
            return SemanticReadinessResult(matches=[])

        if not uploaded_docs:
            # If vault is empty, all required documents are marked missing without an LLM call
            return SemanticReadinessResult(
                matches=[
                    {
                        "required_document": req,
                        "matched_uploaded_id": None,
                        "matched_filename": None,
                        "confidence_reasoning": "No documents uploaded in vault."
                    }
                    for req in required_docs
                ]
            )

        vault_payload = [
            {
                "id": doc.id,
                "document_type": doc.document_type,
                "original_filename": doc.original_filename
            }
            for doc in uploaded_docs
        ]

        prompt = f"""
Official Scheme Required Documents:
{json.dumps(required_docs, indent=2)}

Citizen Uploaded Vault:
{json.dumps(vault_payload, indent=2)}

Evaluate each required document and identify if any uploaded document satisfies it.
"""

        result = await gemini_fast_client.execute_structured_query(
            task_name="SemanticDocMatch",
            prompt=prompt,
            system_instruction=DOCUMENT_MATCHER_PROMPT,
            schema=SemanticReadinessResult
        )

        return result or SemanticReadinessResult(matches=[])


semantic_verifier = DocumentSemanticVerifier()