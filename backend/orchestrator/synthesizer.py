import json
import re

from backend.claude_client import get_adapter
from backend.config import settings

_SYSTEM = """You are the lead consulting architect synthesizing a multi-specialist team's analysis into a final solution document.

You receive a scratchpad JSON containing all agent outputs, locked decisions, and open questions.

Produce a structured solution document as valid JSON matching this schema exactly:
{
  "executive_summary": "string — 2-3 sentences covering the recommended direction",
  "recommended_architecture": "string — detailed architecture recommendation",
  "implementation_plan": [
    {"phase": "string", "description": "string", "duration": "string"}
  ],
  "key_decisions": ["string", ...],
  "risks_and_mitigations": [
    {"risk": "string", "mitigation": "string"}
  ],
  "open_questions": ["string", ...],
  "estimated_timeline": "string"
}

Rules:
- Synthesize ALL agent perspectives — do not omit any specialist's input
- Do not re-open any locked decision from the decision_log
- Be concrete and actionable; avoid generic advice
- Respond with the JSON object ONLY — no markdown, no preamble"""


async def synthesize(session_id: str, scratchpad: dict) -> dict:
    try:
        import logfire
        span_ctx = logfire.span(
            "synthesis",
            session_id=session_id,
            decision_count=len(scratchpad.get("decision_log", [])),
            agent_count=len(scratchpad.get("agent_outputs", {})),
        )
    except Exception:
        from contextlib import nullcontext
        span_ctx = nullcontext()

    with span_ctx:
        adapter = get_adapter()

        # TOKEN RISK: full scratchpad is large. For complex sessions this prompt may exceed
        # 8k tokens. Scratchpad summarization (Phase 5 task 5.6) will cap this at production time.
        scratchpad_text = json.dumps(scratchpad, indent=2)

        response = await adapter.complete(
            system_prompt=_SYSTEM,
            user_prompt=f"Synthesize the following scratchpad into the solution document:\n\n{scratchpad_text}",
            model=settings.model_opus,
            max_tokens=4000,
        )

        text = response.text.strip()
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "executive_summary": "Synthesis completed but JSON parsing failed.",
                "recommended_architecture": text[:2000],
                "implementation_plan": [],
                "key_decisions": [],
                "risks_and_mitigations": [],
                "open_questions": [],
                "estimated_timeline": "Unknown",
            }
