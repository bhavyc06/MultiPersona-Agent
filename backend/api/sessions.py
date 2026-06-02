import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.auth import get_current_user
from backend.db.postgres import get_db
from backend.models import Session, SessionStatus, User

router = APIRouter()

SESSIONS_DIR = Path("data/sessions")


class CreateSessionRequest(BaseModel):
    problem_statement: str


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str


class ClarifyRequest(BaseModel):
    answers: dict[str, str]


@router.post("/sessions", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.problem_statement.strip():
        raise HTTPException(status_code=422, detail="problem_statement must not be empty")

    session = Session(
        user_id=current_user.id,
        problem_statement=body.problem_statement,
        status=SessionStatus.CLARIFYING.value,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    from backend.orchestrator.main_agent import run_session
    asyncio.create_task(
        run_session(str(session.id), body.problem_statement, str(current_user.id))
    )

    return CreateSessionResponse(session_id=str(session.id), status=session.status)


@router.post("/sessions/{session_id}/clarify")
async def submit_clarification(
    session_id: str,
    body: ClarifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(session.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your session")
    if session.status != SessionStatus.CLARIFYING.value:
        raise HTTPException(
            status_code=409,
            detail=f"Session is not awaiting clarification (status={session.status})",
        )

    from backend.orchestrator.clarifier import get_answer_queue
    try:
        get_answer_queue(session_id).put_nowait(body.answers)
    except asyncio.QueueFull:
        raise HTTPException(
            status_code=429,
            detail="Answers already queued — wait for the orchestrator to process them",
        )

    return {"received": True, "session_id": session_id}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": str(session.id),
        "status": session.status,
        "complexity": session.complexity,
        "problem_statement": session.problem_statement,
        "created_at": session.created_at.isoformat(),
    }


@router.get("/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    format: str = "md",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export the solution document as markdown (or PDF stub)."""
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    solution_path = SESSIONS_DIR / session_id / "solution.json"
    if not solution_path.exists():
        raise HTTPException(status_code=404, detail="Solution document not yet available")

    solution = json.loads(solution_path.read_text(encoding="utf-8"))
    md_content = _solution_to_markdown(solution)
    filename = f"solution-{session_id[:8]}.md"

    if format == "pdf":
        # TODO: PDF generation (Phase 5 polish — weasyprint or similar)
        # For now return markdown with .md extension
        return Response(
            content=md_content,
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return Response(
        content=md_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _solution_to_markdown(solution: dict) -> str:
    """Convert solution document dict to readable markdown."""
    if isinstance(solution, str):
        return solution

    lines = ["# Solution Document\n"]

    def _add(heading: str, content):
        if not content:
            return
        lines.append(f"\n## {heading}\n")
        if isinstance(content, str):
            lines.append(content + "\n")
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    for k, v in item.items():
                        lines.append(f"**{k.replace('_',' ').title()}:** {v}\n")
                    lines.append("")
                else:
                    lines.append(f"- {item}\n")

    _add("Executive Summary", solution.get("executive_summary"))
    _add("Recommended Architecture", solution.get("recommended_architecture"))

    if solution.get("implementation_plan"):
        lines.append("\n## Implementation Plan\n")
        for phase in solution["implementation_plan"]:
            lines.append(f"### {phase.get('phase','Phase')}\n")
            if phase.get("description"):
                lines.append(phase["description"] + "\n")
            if phase.get("duration"):
                lines.append(f"*Duration: {phase['duration']}*\n")

    _add("Key Decisions", solution.get("key_decisions"))
    _add("Risks and Mitigations", solution.get("risks_and_mitigations"))
    _add("Open Questions", solution.get("open_questions"))

    if solution.get("estimated_timeline"):
        lines.append("\n## Estimated Timeline\n")
        lines.append(solution["estimated_timeline"] + "\n")

    return "\n".join(lines)
