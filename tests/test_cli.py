"""Quick CLI adapter test — run directly: python tests/test_cli.py"""
import subprocess
import shutil
import json

cmd = shutil.which("claude.cmd") or shutil.which("claude")
print("cmd:", cmd)

combined = (
    "You are a technical complexity classifier.\n\n"
    "Classify: Build a real-time ML feature store. "
    'Respond only with valid JSON: {"complexity": "complex", "reasoning": "test"}'
)

# Test 1: via -p argument
r1 = subprocess.run(
    [cmd, "-p", combined, "--output-format", "json", "--model", "claude-haiku-4-5-20251001"],
    capture_output=True, text=True, encoding="utf-8",
    stdin=subprocess.DEVNULL, timeout=30,
)
print("\n=== -p argument ===")
print("rc:", r1.returncode, "| stdout len:", len(r1.stdout))
print("stdout[:200]:", repr(r1.stdout[:200]))

# Test 2: via stdin (no -p)
r2 = subprocess.run(
    [cmd, "--output-format", "json", "--model", "claude-haiku-4-5-20251001"],
    input=combined,
    capture_output=True, text=True, encoding="utf-8", timeout=30,
)
print("\n=== stdin pipe ===")
print("rc:", r2.returncode, "| stdout len:", len(r2.stdout))
print("stdout[:200]:", repr(r2.stdout[:200]))
