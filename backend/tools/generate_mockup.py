import re
import uuid
from pathlib import Path

from backend.claude_client import get_adapter
from backend.config import settings

_SYSTEM = (
    "You are a UI/UX expert. Generate a complete, self-contained HTML mockup based on the spec.\n\n"
    "Requirements:\n"
    "- Work standalone — NO external CDN links, fonts, or images.\n"
    "- Inline CSS only (no <link> stylesheets). Inline JS only (no <script src>).\n"
    "- Professional, clean, modern design with realistic placeholder data.\n"
    "- Include the key UI elements described in the spec.\n\n"
    "Return ONLY the HTML document starting with <!DOCTYPE html>. "
    "No markdown fences, no explanation, no text before or after the HTML."
)


async def generate_ui_mockup(spec_json: dict) -> dict:
    """
    Sonnet call → self-contained HTML mockup.
    Saves to sessions/{session_id}/mockups/{uuid8}.html.

    # TOKEN RISK: capped at 2000 tokens. Validates HTML starts with <!DOCTYPE html>.
    """
    session_id = spec_json.get("session_id", "shared")
    spec_text = "\n".join(
        f"{k}: {v}" for k, v in spec_json.items() if k != "session_id"
    )

    adapter = get_adapter()
    response = await adapter.complete(
        system_prompt=_SYSTEM,
        user_prompt=f"Generate a UI mockup for:\n\n{spec_text}",
        model=settings.model_sonnet,
        max_tokens=2000,
    )

    html = response.text.strip()

    # Strip markdown fences if the model wraps the HTML
    if html.startswith("```"):
        html = re.sub(r"^```[a-z]*\n?", "", html)
        html = re.sub(r"\n?```$", "", html)

    # Validate and repair
    if not html.upper().lstrip().startswith("<!DOCTYPE"):
        m = re.search(r"<!DOCTYPE", html, re.IGNORECASE)
        if m:
            html = html[m.start():]
        else:
            html = (
                f"<!DOCTYPE html><html><body style='font-family:sans-serif;padding:2rem'>"
                f"<h2>Mockup generation note</h2><pre>{html[:500]}</pre></body></html>"
            )

    mockup_dir = Path(f"data/sessions/{session_id}/mockups")
    mockup_dir.mkdir(parents=True, exist_ok=True)
    artifact_id = str(uuid.uuid4())[:8]
    artifact_path = mockup_dir / f"{artifact_id}.html"
    artifact_path.write_text(html, encoding="utf-8")

    return {
        "artifact_ref": str(artifact_path),
        "preview_html": html[:5000],
    }
