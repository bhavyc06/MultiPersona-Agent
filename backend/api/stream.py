from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.auth import _authenticate_token
from backend.db.postgres import get_db
from backend.models import Session, User
from backend.sse.emitter import session_event_stream

router = APIRouter()


async def _get_stream_user(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Accept JWT from either Authorization header (Swagger/API clients)
    or ?token= query param (EventSource — browsers can't set headers).
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        jwt_token = auth_header[7:]
    elif token:
        jwt_token = token
    else:
        raise HTTPException(status_code=401, detail="Authentication required")

    return await _authenticate_token(jwt_token, db)


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    current_user: User = Depends(_get_stream_user),
    db: AsyncSession = Depends(get_db),
):
    # SECURITY: ownership check — mirrors sessions.py pattern
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(session.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your session")

    return StreamingResponse(
        session_event_stream(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
