"""
backend/graph/contradiction.py — Phase 4: contradiction detector.

Called by supervisor_node after each expert turn to check whether
new proposed decisions conflict with earlier proposed/locked ones.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def _parse_json_safe(text: str, default: dict) -> dict:
    try:
        clean = re.sub(r"```(?:json)?|```", "", text).strip()
        return json.loads(clean)
    except Exception:
        return default


async def detect_contradiction(
    new_proposed: list[str],
    existing_decisions: list[dict],
    enriched_problem: str,
    session_id: str,
) -> dict | None:
    """
    Check whether any of new_proposed contradicts an existing decision
    (state in "proposed" or "locked").

    Returns a conflict dict on first contradiction found:
        {
          "new_decision":        str,  ← what the expert just proposed
          "conflicts_with_id":   str,  ← id of the existing decision
          "conflicts_with_text": str,  ← text of the existing decision
          "conflicts_with_by":   str,  ← role that proposed the existing one
          "summary":             str,  ← plain-English description
        }
    Returns None if no contradiction detected.
    """
    if not new_proposed or not existing_decisions:
        return None

    active = [d for d in existing_decisions if d.get("state") in ("proposed", "locked")]
    if not active:
        return None

    existing_text = "\n".join(
        f"- [{d['id'][:8]}] ({d['state']}) {d['proposed_by']}: {d['text']}"
        for d in active
    )
    new_text = "\n".join(f"- {d}" for d in new_proposed)

    prompt = (
        f"Problem context: {enriched_problem[:200]}\n\n"
        f"Existing decisions:\n{existing_text}\n\n"
        f"Newly proposed decisions:\n{new_text}\n\n"
        "Do any of the NEW decisions directly contradict an EXISTING decision? "
        "A contradiction means both cannot simultaneously be true — "
        "not just a different approach, but a genuine incompatibility "
        "(e.g. 'use PostgreSQL' vs 'use MongoDB', "
        "'synchronous API' vs 'event-driven messaging').\n\n"
        "If yes, return the FIRST contradiction found:\n"
        '{"contradiction": true, '
        '"new_decision": "exact text from new list", '
        '"conflicts_with_id": "8-char id prefix from existing list", '
        '"conflicts_with_text": "exact text from existing list", '
        '"conflicts_with_by": "role name", '
        '"summary": "one sentence plain-English"}\n\n'
        'If no contradiction: {"contradiction": false}'
    )

    from backend.claude_client import get_adapter
    from backend.config import settings

    adapter = get_adapter()
    try:
        resp = await adapter.complete(
            system_prompt=(
                "You are a decision conflict detector. "
                "Return ONLY valid JSON — no prose, no markdown."
            ),
            user_prompt=prompt,
            model=settings.model_sonnet,
            max_tokens=300,
        )
        data = _parse_json_safe(resp.text, {"contradiction": False})
        if not data.get("contradiction"):
            return None

        # Resolve the 8-char prefix to the full decision id
        prefix = data.get("conflicts_with_id", "")
        matched = next(
            (d for d in active if d["id"].startswith(prefix) or d["id"] == prefix),
            None,
        )
        if not matched:
            logger.warning(
                f"[{session_id}] contradiction detected but id prefix "
                f"'{prefix}' not matched in active decisions"
            )
            return None

        result = {
            "new_decision":        data.get("new_decision", ""),
            "conflicts_with_id":   matched["id"],
            "conflicts_with_text": matched["text"],
            "conflicts_with_by":   matched["proposed_by"],
            "summary":             data.get("summary", "Conflicting decisions"),
        }
        logger.info(f"[{session_id}] contradiction found: {result['summary']}")
        return result

    except Exception as exc:
        logger.warning(f"[{session_id}] contradiction detection failed: {exc}")
        return None
