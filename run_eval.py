"""Dead-end PROMPT-discrimination signal: run the fixtures through a real Claude and grade.

Usage:  uv run python run_eval.py

Calls ``claude -p`` per fixture with the transcript inlined as context, grading whether
the recall *prompt* extracts the ratified conclusion rather than the abandoned dead-ends.
This is a fast iteration signal on the prompt — NOT the production path. The canonical
end-to-end gate (real ``--resume`` through ``answerer.run_answerer``) lives in
``tests/test_integration.py`` (run with ``YOINK_INTEGRATION=1``).
"""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from evalkit import build_eval_prompt, grade, load_fixtures
from prompts import parse_answer


def _ask_model(prompt: str, timeout: float = 120) -> str:
    # Prompt goes via stdin: `--tools` is greedy, so a positional prompt after
    # `--tools ""` gets swallowed as a tool name. stdin sidesteps that entirely.
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--tools", ""],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout).get("result", "")


def _evaluate(fixture):
    try:
        raw = _ask_model(build_eval_prompt(fixture))
    except Exception as exc:  # noqa: BLE001 - any model/IO failure is a fixture failure
        return fixture.id, False, [f"model error: {exc}"]
    passed, reasons = grade(fixture, parse_answer(raw))
    return fixture.id, passed, reasons


def main() -> int:
    fixtures = load_fixtures()
    if not fixtures:
        print("no fixtures found")
        return 1

    # The model calls are independent and network-bound — run them concurrently.
    with ThreadPoolExecutor(max_workers=min(8, len(fixtures))) as pool:
        results = sorted(pool.map(_evaluate, fixtures))

    failures = 0
    for fixture_id, passed, reasons in results:
        if passed:
            print(f"PASS {fixture_id}")
        else:
            failures += 1
            print(f"FAIL {fixture_id}: {'; '.join(reasons)}")
    print(f"\n{len(fixtures) - failures}/{len(fixtures)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
