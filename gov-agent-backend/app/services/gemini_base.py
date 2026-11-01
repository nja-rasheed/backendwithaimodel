import time
import logging
import asyncio
from typing import Optional, Type, Any, List
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger("agent.pipeline")

GEMINI_REQUEST_TIMEOUT_SECONDS = 25

# Prioritizing always-available, resilient aliases from your key's verified model list
PRIORITY_MODELS = [
    "gemini-3.5-flash-lite",
]

class GeminiFastClient:
    def __init__(self):
        raw_keys = getattr(settings, "GEMINI_API_KEYS", "") or getattr(settings, "GEMINI_API_KEY", "") or ""
        self.api_keys: List[str] = [k.strip() for k in str(raw_keys).split(",") if k.strip()]

        if not self.api_keys:
            import os
            for i in range(1, 10):
                k = os.getenv(f"GEMINI_API_KEY_{i}")
                if k and k.strip():
                    self.api_keys.append(k.strip())

        self.current_key_idx = 0
        self.total_keys = len(self.api_keys)

        if self.total_keys > 0:
            masked = self._get_masked_key(self.current_key_idx)
            print(f"\033[96m[GeminiClient]\033[0m Loaded {self.total_keys} API key(s). Active Key #{self.current_key_idx} ({masked})")
            logger.info(f"Initialized GeminiFastClient with {self.total_keys} keys.")
            self._init_client()
        else:
            print("\033[91m[GeminiClient]\033[0m WARNING: No Gemini API keys found in settings or environment!")
            logger.warning("No Gemini API keys found.")
            self.client = None

    def _get_masked_key(self, idx: int) -> str:
        if 0 <= idx < len(self.api_keys):
            key = self.api_keys[idx]
            if len(key) > 10:
                return f"{key[:6]}...{key[-4:]}"
            return "******"
        return "N/A"

    def _init_client(self):
        if self.api_keys:
            key = self.api_keys[self.current_key_idx]
            self.client = genai.Client(api_key=key)

    def _rotate_key(self) -> int:
        """Rotates to the next available API key in the pool."""
        if self.total_keys > 1:
            prev_idx = self.current_key_idx
            self.current_key_idx = (self.current_key_idx + 1) % self.total_keys
            masked = self._get_masked_key(self.current_key_idx)
            print(f"\033[93m[GeminiClient]\033[0m Rotated Active Key: Key #{prev_idx} -> Key #{self.current_key_idx} ({masked})")
            logger.warning(f"Rotating Gemini key from #{prev_idx} to #{self.current_key_idx}")
            self._init_client()
        return self.current_key_idx

    async def execute_structured_query(
        self,
        task_name: str,
        prompt: str,
        system_instruction: str,
        schema: Type[BaseModel]
    ) -> Optional[Any]:
        if not self.client or not self.api_keys:
            print(f"\033[91m[{task_name}]\033[0m Aborted: No valid API key configured.")
            logger.warning(f"[{task_name}] No Gemini API key detected.")
            return None

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1,
            max_output_tokens=4096,
            response_mime_type="application/json",
            response_schema=schema,
        )

        overall_start = time.perf_counter()
        key_attempts = max(1, self.total_keys)
        total_attempts = len(PRIORITY_MODELS) * key_attempts
        attempt_number = 0

        print(f"\033[94m[{task_name}]\033[0m Execution started across pool ({self.total_keys} keys available)")

        for model_name in PRIORITY_MODELS:
            for _ in range(key_attempts):
                attempt_number += 1
                active_idx = self.current_key_idx
                active_masked = self._get_masked_key(active_idx)
                print(
                    f"\033[94m[{task_name}]\033[0m [Attempt {attempt_number}/{total_attempts}] "
                    f"Model {model_name} | Key #{active_idx} ({active_masked})"
                )
                model_start = time.perf_counter()
                logger.info(
                    f"[{task_name}] Gemini request started | model={model_name} | key={active_idx}"
                )
                print(
                    f"[{task_name}] Gemini request started | model={model_name} | key={active_idx}"
                )
                try:
                    response = await asyncio.wait_for(
                        self.client.aio.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=config
                        ),
                        timeout=GEMINI_REQUEST_TIMEOUT_SECONDS
                    )
                    model_elapsed = time.perf_counter() - model_start
                    total_elapsed = time.perf_counter() - overall_start
                    logger.info(
                        f"[{task_name}] Gemini response received | model={model_name} | "
                        f"response_time={model_elapsed:.3f}s | total_time={total_elapsed:.3f}s"
                    )
                    print(
                        f"[{task_name}] Gemini response received | model={model_name} | "
                        f"response_time={model_elapsed:.3f}s | total_time={total_elapsed:.3f}s"
                    )

                    if response and response.text:
                        print(
                            f"\033[92m[{task_name}]\033[0m SUCCESS via {model_name} on Key #{active_idx} | "
                            f"Model Time: {model_elapsed:.2f}s | Total Time: {total_elapsed:.2f}s"
                        )
                        logger.info(
                            f"[{task_name}] Finished via {model_name} (Key #{active_idx}) in {model_elapsed:.2f}s (Total: {total_elapsed:.2f}s)"
                        )

                        clean_text = response.text.strip()
                        if clean_text.startswith("```json"):
                            clean_text = clean_text[7:]
                        if clean_text.startswith("```"):
                            clean_text = clean_text[3:]
                        if clean_text.endswith("```"):
                            clean_text = clean_text[:-3]

                        return schema.model_validate_json(clean_text.strip())

                    self._rotate_key()

                except asyncio.TimeoutError:
                    model_elapsed = time.perf_counter() - model_start
                    total_so_far = time.perf_counter() - overall_start
                    self._rotate_key()
                    logger.warning(
                        f"[{task_name}] Gemini request timed out | model={model_name} | "
                        f"timeout={GEMINI_REQUEST_TIMEOUT_SECONDS}s | "
                        f"response_time={model_elapsed:.3f}s | next_key={self.current_key_idx}"
                    )
                    print(
                        f"[{task_name}] Gemini request timed out | model={model_name} | "
                        f"timeout={GEMINI_REQUEST_TIMEOUT_SECONDS}s | "
                        f"response_time={model_elapsed:.3f}s | next_key={self.current_key_idx}"
                    )
                    continue

                except APIError as api_err:
                    print(f"\n[{task_name}] FULL GEMINI API ERROR: {api_err}\n")
                    model_elapsed = time.perf_counter() - model_start
                    total_so_far = time.perf_counter() - overall_start
                    logger.warning(
                        f"[{task_name}] Gemini request failed | model={model_name} | "
                        f"response_time={model_elapsed:.3f}s | error_code={api_err.code}"
                    )
                    print(
                        f"[{task_name}] Gemini request failed | model={model_name} | "
                        f"response_time={model_elapsed:.3f}s | error_code={api_err.code}"
                    )
                    print(
                        f"\033[93m[{task_name}]\033[0m {model_name} APIError {api_err.code} on Key #{active_idx} "
                        f"(Call Time: {model_elapsed:.2f}s, Running Total: {total_so_far:.2f}s)"
                    )
                    logger.warning(f"[{task_name}] {model_name} hit {api_err.code} in {model_elapsed:.2f}s.")

                    self._rotate_key()
                    continue

                except Exception as e:
                    model_elapsed = time.perf_counter() - model_start
                    total_so_far = time.perf_counter() - overall_start
                    logger.warning(
                        f"[{task_name}] Gemini request failed | model={model_name} | "
                        f"response_time={model_elapsed:.3f}s | error={str(e)[:100]}"
                    )
                    print(
                        f"[{task_name}] Gemini request failed | model={model_name} | "
                        f"response_time={model_elapsed:.3f}s | error={str(e)[:100]}"
                    )
                    print(
                        f"\033[91m[{task_name}]\033[0m {model_name} Exception on Key #{active_idx}: {str(e)[:100]} "
                        f"(Call Time: {model_elapsed:.2f}s, Running Total: {total_so_far:.2f}s)"
                    )
                    logger.warning(f"[{task_name}] {model_name} unexpected error: {str(e)[:100]}")
                    self._rotate_key()
                    continue

        total_elapsed = time.perf_counter() - overall_start
        print(f"\033[91m[{task_name}]\033[0m FAILED: All {self.total_keys} keys exhausted. Total Time Taken: {total_elapsed:.2f}s")
        logger.error(f"[{task_name}] All dynamic attempts exhausted in {total_elapsed:.2f}s.")
        return None


gemini_fast_client = GeminiFastClient()