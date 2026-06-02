async def fetch_memory(user_id: str, query: str) -> list[dict]:
    """
    Retrieve relevant prior session summaries for this user.
    Returns [] if no memories exist or none exceed the similarity threshold (0.65).
    NEVER returns another user's memories.
    """
    from backend.memory.session_memory import get_relevant_memories
    memories = await get_relevant_memories(user_id, query)
    return [{"summary": m, "source": "prior_session"} for m in memories]
