"""
Diagnostic: show similarity scores for the yoga-studio problem against
all stored memories for the test user, at threshold 0.65 (before) and
0.82 (after). Run with: python check_memory.py
"""
import asyncio, sys, os

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv; load_dotenv()

YOGA_PROBLEM = (
    "Build a booking system for a small yoga studio: class schedules, "
    "member sign-ups, waitlists, instructor payouts. No existing tools. "
    "~200 members. Owner is non-technical. Budget $100/month."
)

TEST_USER_EMAIL = "phase0test@test.com"

THRESHOLD_OLD  = 0.65
THRESHOLD_NEW  = 0.82


async def run():
    import uuid as _uuid
    import numpy as np
    from sqlalchemy import select
    from backend.db.postgres import AsyncSessionLocal
    from backend.models import MemoryEntry, User
    from backend.memory.encryption import decrypt_text
    from backend.rag.service import get_rag_service

    # Resolve user_id for test account
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.email == TEST_USER_EMAIL)
        )
        user = result.scalar_one_or_none()

    if not user:
        print(f"User {TEST_USER_EMAIL!r} not found in DB.")
        return

    user_id = str(user.id)
    print(f"User: {TEST_USER_EMAIL}  id={user_id}")

    # Embed the yoga problem
    svc = get_rag_service()
    query_vec = await asyncio.to_thread(svc.embed, YOGA_PROBLEM)

    # Fetch all memory entries for this user
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MemoryEntry).where(MemoryEntry.user_id == _uuid.UUID(user_id))
        )
        entries = result.scalars().all()

    if not entries:
        print("No memory entries found for this user.")
        return

    # Score all entries
    def cosine(a, b):
        va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        return float(np.dot(va, vb) / (na * nb)) if na and nb else 0.0

    scored = []
    for e in entries:
        if e.embedding is None:
            continue
        sim = cosine(query_vec, list(e.embedding))
        try:
            summary = decrypt_text(e.summary)[:80]
        except Exception:
            summary = "(decrypt failed)"
        scored.append((sim, summary, str(e.session_id)))

    scored.sort(reverse=True)

    print(f"\nYoga problem vs all {len(scored)} memory entries:")
    print(f"{'SIM':>6}  {'ABOVE_OLD':>9}  {'ABOVE_NEW':>9}  SUMMARY (first 80 chars)")
    print("-" * 110)
    for sim, summary, sid in scored:
        above_old = "INJECT" if sim >= THRESHOLD_OLD else "skip"
        above_new = "INJECT" if sim >= THRESHOLD_NEW else "skip"
        flag = " *** DIFF ***" if above_old != above_new else ""
        print(f"{sim:6.3f}  {above_old:>9}  {above_new:>9}  {summary!r}{flag}")

    injected_old = [s for s,_,_ in scored if s >= THRESHOLD_OLD][:2]
    injected_new = [s for s,_,_ in scored if s >= THRESHOLD_NEW][:2]
    print(f"\n  OLD threshold ({THRESHOLD_OLD}): {len(injected_old)} entries injected  scores={[round(s,3) for s in injected_old]}")
    print(f"  NEW threshold ({THRESHOLD_NEW}): {len(injected_new)} entries injected  scores={[round(s,3) for s in injected_new]}")


asyncio.run(run())
