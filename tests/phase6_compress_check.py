"""
Phase 6 compress check — verifies compress_session reads from DB (not scratchpad)
and writes a decryptable MemoryEntry row.

Usage:
    python tests/phase6_compress_check.py

Requires: a completed session in the sessions table (run a full session first).
Uses sync psycopg2 for DB queries; asyncio.run for the async compress call.
"""
import asyncio
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL_SYNC = os.environ["DATABASE_URL"].replace("+asyncpg", "")


def get_latest_completed_session():
    conn = psycopg2.connect(DATABASE_URL_SYNC)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id::text, user_id::text
        FROM sessions
        WHERE status = 'completed'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row  # (session_id, user_id) or None


def get_memory_entry_for_session(session_id: str):
    conn = psycopg2.connect(DATABASE_URL_SYNC)
    cur = conn.cursor()
    cur.execute(
        "SELECT id::text, summary FROM memory_entries WHERE session_id = %s",
        (session_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row  # (id, encrypted_summary) or None


def get_public_message_count(session_id: str) -> int:
    conn = psycopg2.connect(DATABASE_URL_SYNC)
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM agent_messages WHERE session_id = %s AND is_private = false",
        (session_id,),
    )
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


async def run_compress(session_id: str, user_id: str):
    from backend.memory.compressor import compress_session
    return await compress_session(session_id, user_id)


def main():
    row = get_latest_completed_session()
    if not row:
        print("FAIL: no completed sessions in DB — run a full session first")
        sys.exit(1)

    session_id, user_id = row
    print(f"Session:  {session_id}")
    print(f"User:     {user_id}")

    msg_count = get_public_message_count(session_id)
    print(f"Public messages in DB: {msg_count}")
    if msg_count == 0:
        print("FAIL: session has no public agent_messages rows")
        sys.exit(1)

    print("Running compress_session...")
    result = asyncio.run(run_compress(session_id, user_id))

    if result is None:
        print("FAIL: compress_session returned None — check application logs")
        sys.exit(1)

    print(f"OK  MemoryEntry written: id={result.id}")

    db_row = get_memory_entry_for_session(session_id)
    if not db_row:
        print("FAIL: MemoryEntry not found in DB after compress (commit may have failed)")
        sys.exit(1)

    print(f"OK  DB row confirmed: memory_entries.id={db_row[0]}")

    from backend.memory.encryption import decrypt_text
    try:
        summary = decrypt_text(db_row[1])
    except Exception as exc:
        print(f"FAIL: could not decrypt summary: {exc}")
        sys.exit(1)

    print(f"OK  Decrypted summary ({len(summary)} chars):")
    print("-" * 60)
    print(summary[:500])
    print("-" * 60)
    print("Phase 6 compress check PASSED")


if __name__ == "__main__":
    main()
