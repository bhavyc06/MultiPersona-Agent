"""
V5-D: per-user persona library — the SAVE half.

Save / list / delete endpoints for dynamically recruited experts. Every query
is scoped to the authenticated user_id — personas never leak across users.
The cross-session suggestion/auto-add logic is DEFERRED (out of scope).
"""
import logging
import uuid as uuid_module

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.auth import get_current_user
from backend.db.postgres import get_db
from backend.models import User, UserPersona

logger = logging.getLogger(__name__)
router = APIRouter()

# Soft cap on saved personas per user (STEP 1).
LIBRARY_SOFT_CAP = 20

# Core-8 experts are always available and are NOT savable.
_CORE_8 = {
    "ai_architect", "solution_architect", "data_engineer", "data_scientist",
    "ai_engineer", "solution_engineer", "ui_builder", "project_manager",
}


class SavePersonaRequest(BaseModel):
    role: str
    display_name: str
    domain: str
    domain_lock_prompt: str = ""
    default_level: str = "L1"
    source_session_id: str | None = None


def _serialize(p: UserPersona) -> dict:
    return {
        "id":                 str(p.id),
        "role":               p.role,
        "display_name":       p.display_name,
        "domain":             p.domain,
        "default_level":      p.default_level,
        "source_session_id":  str(p.source_session_id) if p.source_session_id else None,
        "use_count":          p.use_count,
        "created_at":         p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/library/personas")
async def list_personas(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the authenticated user's saved specialists (newest first)."""
    result = await db.execute(
        select(UserPersona)
        .where(UserPersona.user_id == current_user.id)
        .order_by(UserPersona.created_at.desc())
    )
    return {"personas": [_serialize(p) for p in result.scalars().all()]}


@router.post("/library/personas", status_code=201)
async def save_persona(
    body: SavePersonaRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a RECRUITED expert to the user's library.

    - Core-8 roles are rejected (always available; never saved).
    - Saving the same role twice is a dedup no-op (returns the existing row).
    - Enforces the 20-persona soft cap on genuinely new saves.
    """
    role = body.role.strip()
    if not role:
        raise HTTPException(status_code=422, detail="role must not be empty")
    if role in _CORE_8:
        raise HTTPException(
            status_code=400,
            detail="Core experts are always available and cannot be saved to the library.",
        )

    # Dedup: same (user, role) → no-op, return existing row.
    existing = await db.execute(
        select(UserPersona).where(
            UserPersona.user_id == current_user.id,
            UserPersona.role == role,
        )
    )
    found = existing.scalar_one_or_none()
    if found:
        return {"persona": _serialize(found), "created": False, "deduped": True}

    # Soft cap — only counts against NEW saves (dedup above already returned).
    count_res = await db.execute(
        select(func.count()).select_from(UserPersona).where(
            UserPersona.user_id == current_user.id
        )
    )
    if (count_res.scalar() or 0) >= LIBRARY_SOFT_CAP:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Your library is full ({LIBRARY_SOFT_CAP} specialists). "
                "Delete one before saving another."
            ),
        )

    src_uuid = None
    if body.source_session_id:
        try:
            src_uuid = uuid_module.UUID(body.source_session_id)
        except (ValueError, AttributeError):
            src_uuid = None

    persona = UserPersona(
        user_id=current_user.id,
        role=role,
        display_name=body.display_name.strip() or role,
        domain=body.domain.strip() or role,
        domain_lock_prompt=body.domain_lock_prompt or "",
        default_level=body.default_level if body.default_level in ("L1", "L2", "L3") else "L1",
        source_session_id=src_uuid,
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    logger.info(
        "[library] user=%s saved persona role=%r (from session=%s)",
        current_user.id, role, body.source_session_id,
    )
    return {"persona": _serialize(persona), "created": True, "deduped": False}


@router.delete("/library/personas/{persona_id}")
async def delete_persona(
    persona_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a saved persona — scoped to the owner."""
    try:
        pid = uuid_module.UUID(persona_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Invalid persona id")

    result = await db.execute(
        select(UserPersona).where(
            UserPersona.id == pid,
            UserPersona.user_id == current_user.id,
        )
    )
    persona = result.scalar_one_or_none()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    await db.delete(persona)
    await db.commit()
    return {"deleted": True, "id": persona_id}
