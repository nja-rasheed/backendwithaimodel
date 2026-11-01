import os

from google import genai

from browser_agent.intelligence.prompt_builder import build_prompt
from browser_agent.intelligence.response_parser import parse_model_response


class DecisionEngineError(Exception):
    pass


class DecisionEngine:

    def __init__(self, model="gemini-flash-lite-latest", api_key=None):

        resolved_key = api_key or os.getenv("GEMINI_API_KEY")

        if not resolved_key:
            raise DecisionEngineError(
                "GEMINI_API_KEY is not configured"
            )

        self.client = genai.Client(api_key=resolved_key)
        self.model = model

    def decide(self, task, observation):

        prompt = build_prompt(task, observation)

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt["user_content"],
                config={
                    "system_instruction": prompt["system_instruction"],
                    "temperature": 0,
                    "response_mime_type": "application/json",
                },
            )

        except Exception as error:
            raise DecisionEngineError(
                "Model request failed"
            ) from error

        if not response.text:
            raise DecisionEngineError("Model returned an empty response")

        try:
            return parse_model_response(response.text)

        except Exception as error:
            raise DecisionEngineError(
                "Model returned an invalid action"
            ) from error