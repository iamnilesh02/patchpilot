import json
import os
import time
from typing import Dict, Any, Tuple, Optional
from openai import OpenAI
from pydantic import BaseModel


class InferenceTelemetry(BaseModel):
    model: str
    tier: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    cost_usd: float


class NebiusTokenFactoryClient:
    """Manages OpenAI-compatible API interaction, cascaded model routing, and pricing."""

    # Nebius Token Factory pricing rates per 1M tokens
    MODEL_RATES = {
        "nebius/nvidia/Nemotron-3_5-Lightning": {"input": 0.06, "output": 0.24},
        "nebius/nvidia/nemotron-3-super-120b-a12b": {"input": 0.30, "output": 0.90},
        "nebius/nvidia/Nemotron-3-Ultra-550b-a55b": {"input": 1.00, "output": 3.00},
    }

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("NEBIUS_API_KEY", "")
        self.base_url = base_url or os.getenv(
            "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"
        )
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    def route_tier(self, exception_type: str, iteration: int) -> Tuple[str, int]:
        """Tier 1 handles single-scope errors; Tier 2 handles structural or retry regressions."""
        tier1_errors = {"IndexError", "TypeError", "ZeroDivisionError", "KeyError", "ValueError"}
        if iteration > 1 or exception_type not in tier1_errors:
            return "nebius/nvidia/nemotron-3-super-120b-a12b", 2
        return "nebius/nvidia/Nemotron-3_5-Lightning", 1

    def generate_patch(
        self,
        condensed_ast_context: str,
        full_source_code: str,
        relative_path: str,
        exception_type: str,
        iteration: int = 1,
    ) -> Tuple[Dict[str, Any], InferenceTelemetry]:
        model, tier = self.route_tier(exception_type, iteration)

        system_prompt = (
            "You are PatchPilot, an autonomous SWE agent. Fix the bug without breaking API contracts.\n"
            "Return strictly valid JSON with this schema:\n"
            "{\n"
            '  "diagnosis": "Root cause summary",\n'
            '  "relative_path": "path/to/file.py",\n'
            '  "replacement_code": "Complete replacement code for the entire file"\n'
            "}\n"
            "Never modify or remove existing test files."
        )

        user_content = (
            f"FAILURE CONTEXT:\n{condensed_ast_context}\n\n"
            f"CURRENT FILE CONTENT ({relative_path}):\n```python\n{full_source_code}\n```"
        )

        start = time.perf_counter()
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        latency = (time.perf_counter() - start) * 1000.0

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = prompt_tokens + completion_tokens

        rates = self.MODEL_RATES.get(model, {"input": 0.30, "output": 0.90})
        cost = (prompt_tokens * rates["input"] / 1e6) + (completion_tokens * rates["output"] / 1e6)

        telemetry = InferenceTelemetry(
            model=model,
            tier=tier,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency,
            cost_usd=cost,
        )

        payload = json.loads(response.choices[0].message.content)
        return payload, telemetry