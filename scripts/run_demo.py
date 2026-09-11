#!/usr/bin/env python3
"""Run the agent end-to-end on the canonical demo question and save a full
transcript + report under backend/reports/, so there is always a
re-playable artifact even if a live API is unavailable during judging.

Usage: python scripts/run_demo.py ["custom question"]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.loop import run_agent  # noqa: E402
from scripts.validate_citations import analyze_report  # noqa: E402

DEFAULT_QUESTION = (
    "Does activating SIRT1 plausibly extend human healthspan via improved "
    "mitochondrial biogenesis, and what is the strongest next experiment to "
    "test that mechanism?"
)

REPORTS_DIR = Path(__file__).resolve().parent.parent / "backend" / "reports"


def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTION
    print(f"Question: {question}\n")

    def on_event(event: dict) -> None:
        t = event.get("type")
        if t == "phase":
            print(f"\n=== PHASE: {event['phase']} ===")
        elif t == "tool_call":
            print(f"  -> CALL {event['tool']}({event['args']})")
        elif t == "tool_result":
            mock = " [MOCK]" if event.get("mock") else ""
            print(f"  <- RESULT {event['tool']}{mock}: {event['summary'][:200]}")
        elif t == "assistant_text":
            print(f"  [reasoning] {event['text'][:300]}")
        elif t == "error":
            print(f"  !! ERROR: {event['error']}")
        elif t == "done":
            print("\n=== DONE ===")

    started = time.time()
    result = run_agent(question, on_event=on_event)
    elapsed = time.time() - started

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / f"demo_{result['run_id']}.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    report_md_path = REPORTS_DIR / f"demo_{result['run_id']}.md"
    report_md_path.write_text(result["report"])

    print(f"\nElapsed: {elapsed:.1f}s")
    print(f"Saved transcript: {out_path}")
    print(f"Saved report: {report_md_path}")

    print("\n--- Citation coverage check ---")
    analysis = analyze_report(result["report"], set(result.get("evidence", {}).keys()))
    print(f"Coverage: {analysis['coverage']:.1%} "
          f"({analysis['cited_sentences']}/{analysis['total_sentences']} sentences)")
    if analysis["unresolved_citation_markers"]:
        print(f"Unresolved citation markers: {analysis['unresolved_citation_markers']}")


if __name__ == "__main__":
    main()
