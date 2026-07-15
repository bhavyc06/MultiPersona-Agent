"""
Step 1: Direct Bedrock converse() test for all three new us-west-1 ARNs.
STOP if any call returns ValidationException, AccessDenied, region error,
or malformed-ARN error. Only proceed to config changes if ALL THREE pass.
"""
import asyncio, sys, time

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()

NEW_REGION = "us-west-1"

ARNS = {
    "Opus (deep)":      "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/ejpjsea13wpw",
    "Sonnet (shallow)": "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/wxs8vfomtgt9",
    "Haiku (utility)":  "arn:aws:bedrock:us-west-1:654654399581:application-inference-profile/drf1d6igxbea",
}

SYSTEM = "You are a test assistant."
USER   = "Reply with exactly the word OK and nothing else."


async def test_arn(label: str, arn: str) -> dict:
    import aioboto3
    session = aioboto3.Session()
    t0 = time.monotonic()
    try:
        async with session.client("bedrock-runtime", region_name=NEW_REGION) as client:
            raw = await client.converse(
                modelId=arn,
                system=[{"text": SYSTEM}],
                messages=[{"role": "user", "content": [{"text": USER}]}],
                inferenceConfig={"maxTokens": 16, "temperature": 0.0},
            )
        elapsed = round((time.monotonic() - t0) * 1000)
        text = raw["output"]["message"]["content"][0]["text"].strip()
        tokens_in  = raw["usage"]["inputTokens"]
        tokens_out = raw["usage"]["outputTokens"]
        return {
            "label":   label,
            "arn":     arn,
            "ok":      True,
            "text":    text,
            "in":      tokens_in,
            "out":     tokens_out,
            "ms":      elapsed,
            "error":   None,
        }
    except Exception as exc:
        elapsed = round((time.monotonic() - t0) * 1000)
        return {
            "label": label,
            "arn":   arn,
            "ok":    False,
            "text":  None,
            "in":    0,
            "out":   0,
            "ms":    elapsed,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def run():
    print(f"\n══════════════════════════════════════════════")
    print(f"Step 1 — Direct Bedrock test, region={NEW_REGION}")
    print(f"══════════════════════════════════════════════\n")

    results = []
    for label, arn in ARNS.items():
        print(f"  Testing {label} ...", end=" ", flush=True)
        r = await test_arn(label, arn)
        results.append(r)
        if r["ok"]:
            print(f"PASS  reply={r['text']!r}  in={r['in']} out={r['out']} ms={r['ms']}")
        else:
            print(f"FAIL")
            print(f"    ARN:   {arn}")
            print(f"    Error: {r['error']}")

    print("\n── Summary ──")
    all_pass = all(r["ok"] for r in results)
    for r in results:
        status = "PASS" if r["ok"] else "FAIL"
        print(f"  {status}  {r['label']:20s}  {r['ms']:5d}ms")

    if all_pass:
        print("\n✓ ALL THREE ARNs reachable in us-west-1 — safe to proceed with config changes.")
    else:
        print("\n✗ ONE OR MORE ARNs FAILED — DO NOT touch config. Report errors above.")

    return all_pass


if __name__ == "__main__":
    ok = asyncio.run(run())
    sys.exit(0 if ok else 1)
