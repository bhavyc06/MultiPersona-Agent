import asyncio, selectors, json
from dotenv import load_dotenv; load_dotenv()

async def check():
    import psycopg
    conn = await psycopg.AsyncConnection.connect(
        'host=localhost port=5432 dbname=consulting_sim user=user password=pass',
        autocommit=True
    )
    # All decisions mentioning receipt/expense/OCR
    cur = await conn.execute("""
        SELECT d.session_id::text, d.proposed_by, d.state, LEFT(d.text, 120)
        FROM decisions d
        WHERE d.text ILIKE '%receipt%' OR d.text ILIKE '%expense%' OR d.text ILIKE '%OCR%'
        ORDER BY d.session_id, d.created_at LIMIT 30
    """)
    rows = await cur.fetchall()
    print(f'Receipt/expense/OCR decisions across ALL sessions ({len(rows)}):')
    for r in rows:
        print(f'  session={r[0][:8]} proposed_by={r[1]} state={r[2]}')
        print(f'    {r[3]}')
        print()

    # Check which sessions have product_manager_specialist as proposed_by
    cur2 = await conn.execute("""
        SELECT d.session_id::text, d.state, COUNT(*)
        FROM decisions d
        WHERE d.proposed_by = 'product_manager_specialist'
        GROUP BY d.session_id, d.state
    """)
    rows2 = await cur2.fetchall()
    print('product_manager_specialist decisions by session:')
    for r in rows2:
        print(f'  session={r[0][:8]} state={r[1]} count={r[2]}')

    await conn.close()

asyncio.run(check(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
