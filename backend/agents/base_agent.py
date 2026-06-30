from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentDefinition:
    role: str           # snake_case identifier, matches .claude/agents/<role>.md
    display_name: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    model: str = ""
    max_tokens: int = 2000


def load_system_prompt(role: str) -> str:
    path = Path(".claude/agents") / f"{role}.md"
    if not path.exists():
        raise FileNotFoundError(f"Agent system prompt not found: {path}")
    return path.read_text()

