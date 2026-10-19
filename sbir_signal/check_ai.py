"""Check that the GEMINI_API_KEY secret works, without building an issue.

    python -m sbir_signal.check_ai

Exits with an error (a red X on GitHub) if the key is missing or rejected.
"""

from __future__ import annotations

import os
import sys

from . import config
from .summarize import _call_gemini

PROMPT = 'Reply with JSON only: {"ok": true, "note": "<three words about SBIR>"}'


def main() -> int:
    if not config.GEMINI_API_KEY:
        return _report(False, "No GEMINI_API_KEY secret found. Add it under Settings, Secrets and variables, Actions.")
    try:
        result, model = _call_gemini(PROMPT)
    except RuntimeError as exc:
        return _report(False, str(exc))
    if not isinstance(result, dict) or result.get("ok") is not True:
        return _report(False, f"Gemini ({model}) answered, but not in the expected format: {str(result)[:120]}")
    return _report(True, f"Gemini key works. Model used: {model}.")


def _report(ok: bool, message: str) -> int:
    line = ("PASS: " if ok else "FAIL: ") + message
    print(line)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
