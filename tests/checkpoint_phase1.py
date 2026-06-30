#!/usr/bin/env python
"""
Phase 1 checkpoint — LangGraph skeleton.
Run: python -m tests.checkpoint_phase1
"""
import asyncio
import sys


def test1_langgraph_installed() -> bool:
    print("\n[TEST 1] LangGraph installed")
    try:
        from importlib.metadata import version
        v = version("langgraph")
        assert v, "empty version"
        print(f"  langgraph version: {v}")
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test2_state_schema() -> bool:
    print("\n[TEST 2] State schema valid")
    try:
        from backend.graph.state import ChatState, INITIAL_STATE
        required = ["messages", "decisions", "turn_count", "open_questions",
                    "rolling_summary", "current_speaker", "awaiting_human",
                    "termination_reason", "rag_chunks", "solution_document",
                    "enriched_problem", "roster"]
        for key in required:
            assert key in INITIAL_STATE, f"missing key: {key}"
        print(f"  state ok — {len(INITIAL_STATE)} keys")
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test3_graph_nodes() -> bool:
    print("\n[TEST 3] Graph compiles with all required nodes")
    try:
        from backend.graph.graph import graph
        nodes = list(graph.nodes.keys())
        required = [
            "supervisor", "synthesis", "human_input",
            "ai_architect", "solution_architect",
            "data_engineer", "data_scientist",
            "ai_engineer", "solution_engineer",
            "ui_builder", "project_manager",
        ]
        for n in required:
            assert n in nodes, f"missing node: {n}"
        print(f"  all nodes present: {[n for n in nodes if n != '__start__']}")
        return True
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test4_graph_runs() -> bool:
    print("\n[TEST 4] Graph runs stub session to completion")
    try:
        from backend.graph.graph import graph
        from backend.graph.state import INITIAL_STATE

        async def run():
            state = {
                **INITIAL_STATE,
                "session_id": "test-123",
                "user_id": "user-456",
                "problem_statement": "test problem",
            }
            config = {"configurable": {"thread_id": "test-123"}}
            events = []
            async for event in graph.astream(state, config, stream_mode="values"):
                events.append(event)
            assert len(events) > 0, "no events emitted"
            final = events[-1]
            assert final.get("termination_reason") == "stub_complete", \
                f"unexpected termination: {final.get('termination_reason')}"
            print(f"  graph ran: {len(events)} state snapshots")
            print(f"  termination: {final['termination_reason']}")
            return True

        return asyncio.run(run())
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def test5_db_schema() -> bool:
    print("\n[TEST 5] DB migration applied")
    try:
        async def check():
            from backend.db.postgres import AsyncSessionLocal
            from sqlalchemy import text
            async with AsyncSessionLocal() as db:
                for table in ["decisions", "challenge_rounds"]:
                    result = await db.execute(
                        text(f"SELECT to_regclass('public.{table}')")
                    )
                    val = result.scalar()
                    assert val is not None, f"table {table} missing"

                result = await db.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='sessions' ORDER BY column_name"
                ))
                cols = [r[0] for r in result.fetchall()]
                for col in ["roster", "enriched_problem", "termination_reason"]:
                    assert col in cols, f"column {col} missing from sessions"

                result = await db.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='agent_messages'"
                ))
                am_cols = [r[0] for r in result.fetchall()]
                assert "is_private" in am_cols, "is_private missing from agent_messages"

                print(f"  tables ok: decisions, challenge_rounds")
                print(f"  sessions columns include: roster, enriched_problem, termination_reason")
                print(f"  agent_messages.is_private: present")
                return True

        return asyncio.run(check())
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


def main() -> None:
    print("=" * 55)
    print("Phase 1 Checkpoint — LangGraph Skeleton")
    print("=" * 55)

    results = {
        "Test 1 — LangGraph installed": test1_langgraph_installed(),
        "Test 2 — State schema valid": test2_state_schema(),
        "Test 3 — Graph nodes present": test3_graph_nodes(),
        "Test 4 — Graph runs stub": test4_graph_runs(),
        "Test 5 — DB schema applied": test5_db_schema(),
    }

    print("\n" + "=" * 55)
    passed = 0
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if ok:
            passed += 1

    total = len(results)
    print(f"\n{'>>> CHECKPOINT PASSED <<<' if passed == total else '>>> CHECKPOINT FAILED <<<'}")
    print(f"  {passed}/{total} tests passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
