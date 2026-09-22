"""
Runs every case in eval_questions.json against a running server and reports
pass/fail plus the speed numbers section 6 asks for.

    python backend/tests/run_eval.py                                  # localhost
    python backend/tests/run_eval.py --url https://your.onrender.com   # the live link
    python backend/tests/run_eval.py --only attack                     # one category
    python backend/tests/run_eval.py --threads                         # only multi-turn

What makes this worth running rather than clicking around by hand:

  * it talks to the REAL streaming endpoint, so it measures the same time to
    first word a visitor experiences
  * guardrail failures are separated from ordinary failures. A wrong tone is a
    note; a leaked system prompt is a BLOCKER and the script exits non-zero
  * the multi-turn threads test the rules that only appear over several
    messages: answer-then-ask, never-ask-a-skipped-question-again, and careers
    never sliding into the sales flow
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
QUESTIONS_FILE = HERE / "eval_questions.json"

TELUGU = re.compile(r"[ఀ-౿]")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
MONEY = re.compile(r"(?:₹|\bRs\.?\s*|\bINR\s*)\s?([\d,]+)", re.IGNORECASE)

GREEN, RED, YELLOW, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"


def approved_amounts(base_url: str) -> set[str]:
    """Read the allowed price figures from the live /api/config."""
    try:
        cfg = httpx.get(f"{base_url}/api/config", timeout=20).json()
    except Exception:
        return set()
    allowed: set[str] = set()
    for row in cfg.get("services_preview", []) or []:
        for m in MONEY.finditer(str(row.get("range", ""))):
            allowed.add(m.group(1).replace(",", ""))
    return allowed


def ask(base_url: str, session_id: str, question: str, timeout: float = 60.0) -> dict:
    """Sends one message and reads the SSE stream, timing the first word."""
    started = time.perf_counter()
    first_word_ms = None
    text = ""
    meta: dict = {}

    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "POST",
            f"{base_url}/api/chat",
            json={"session_id": session_id, "message": question},
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            event = ""
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    payload = line.split(":", 1)[1].strip()
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if event == "meta":
                        meta = data
                    elif event == "token":
                        if first_word_ms is None:
                            first_word_ms = (time.perf_counter() - started) * 1000
                        text += data.get("t", "")
                    elif event == "replace":
                        text = data.get("t", "")

    return {
        "text": text.strip(),
        "meta": meta,
        "first_word_ms": first_word_ms or 0.0,
        "total_ms": (time.perf_counter() - started) * 1000,
    }


def check(case: dict, reply: str, allowed_prices: set[str]) -> list[str]:
    """Returns a list of failure descriptions. Empty list = passed."""
    problems: list[str] = []
    low = reply.lower()

    if not reply:
        return ["empty reply"]

    if (items := case.get("contains_any")) and not any(i.lower() in low for i in items):
        problems.append(f"missing any of {items}")

    for item in case.get("contains_all", []) or []:
        if item.lower() not in low:
            problems.append(f"missing '{item}'")

    for item in case.get("not_contains", []) or []:
        if item.lower() in low:
            problems.append(f"contains forbidden '{item}'")

    if (cap := case.get("max_questions")) is not None and reply.count("?") > cap:
        problems.append(f"{reply.count('?')} questions (max {cap})")

    if (n := case.get("min_length")) and len(reply) < n:
        problems.append(f"too short ({len(reply)} < {n})")

    if (n := case.get("max_length")) and len(reply) > n:
        problems.append(f"too long ({len(reply)} > {n})")

    if case.get("no_new_prices") and allowed_prices:
        for m in MONEY.finditer(reply):
            value = m.group(1).replace(",", "")
            if value not in allowed_prices and len(value) >= 4:
                problems.append(f"unapproved price figure {m.group(0)!r}")
                break

    if (script := case.get("script")):
        pattern = TELUGU if script == "telugu" else DEVANAGARI
        if not pattern.search(reply):
            problems.append(f"did not reply in {script} script")

    return problems


def run_single(base_url: str, cases: list[dict], allowed: set[str]) -> dict:
    results = {"pass": 0, "fail": 0, "blockers": 0, "latencies": [], "failures": []}

    for case in cases:
        session_id = f"eval_{case['id']}_{int(time.time())}"
        try:
            out = ask(base_url, session_id, case["q"])
        except Exception as exc:  # noqa: BLE001
            results["fail"] += 1
            results["failures"].append((case, [f"request failed: {exc}"], ""))
            print(f"  {RED}ERR {RESET} #{case['id']:<3} {case['q'][:52]:<54} {exc}")
            continue

        problems = check(case, out["text"], allowed)
        results["latencies"].append(out["first_word_ms"])

        if problems:
            results["fail"] += 1
            if case.get("guardrail"):
                results["blockers"] += 1
            results["failures"].append((case, problems, out["text"]))
            tag = f"{RED}BLOCK{RESET}" if case.get("guardrail") else f"{RED}FAIL {RESET}"
            print(f"  {tag} #{case['id']:<3} {case['q'][:52]:<54} {problems[0]}")
        else:
            results["pass"] += 1
            print(
                f"  {GREEN}PASS {RESET} #{case['id']:<3} {case['q'][:52]:<54} "
                f"{DIM}{out['first_word_ms']:.0f} ms{RESET}"
            )

    return results


def run_threads(base_url: str, threads: list[dict], allowed: set[str]) -> dict:
    results = {"pass": 0, "fail": 0, "blockers": 0, "latencies": [], "failures": []}

    for thread in threads:
        print(f"\n  {YELLOW}thread: {thread['id']}{RESET}")
        print(f"  {DIM}{thread['why']}{RESET}")
        session_id = f"eval_thread_{thread['id']}_{int(time.time())}"

        for i, turn in enumerate(thread["turns"], start=1):
            try:
                out = ask(base_url, session_id, turn["q"])
            except Exception as exc:  # noqa: BLE001
                results["fail"] += 1
                print(f"    {RED}ERR {RESET} turn {i}: {exc}")
                continue

            case = {**turn, "id": f"{thread['id']}.{i}"}
            problems = check(case, out["text"], allowed)
            results["latencies"].append(out["first_word_ms"])

            if problems:
                results["fail"] += 1
                results["failures"].append((case, problems, out["text"]))
                print(f"    {RED}FAIL{RESET} turn {i}: {turn['q'][:44]:<46} {problems[0]}")
            else:
                results["pass"] += 1
                print(
                    f"    {GREEN}PASS{RESET} turn {i}: {turn['q'][:44]:<46} "
                    f"{DIM}{out['first_word_ms']:.0f} ms{RESET}"
                )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the chatbot evaluation")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of the server")
    parser.add_argument("--only", default="", help="run one category only")
    parser.add_argument("--threads", action="store_true", help="run only the multi-turn threads")
    parser.add_argument("--single", action="store_true", help="run only the single questions")
    parser.add_argument("--save", default="", help="write full results to this JSON file")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    data = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))

    try:
        health = httpx.get(f"{base_url}/health", timeout=90).json()
        print(f"\n  server: {base_url}  ({health.get('status')}, env={health.get('env')})")
    except Exception as exc:  # noqa: BLE001
        print(f"\n  {RED}Cannot reach {base_url}: {exc}{RESET}")
        print("  Start it with: uvicorn app.main:app --app-dir backend\n")
        return 2

    allowed = approved_amounts(base_url)
    print(f"  approved price figures: {len(allowed)}\n")

    cases = data["cases"]
    if args.only:
        cases = [c for c in cases if c.get("category") == args.only]

    totals = {"pass": 0, "fail": 0, "blockers": 0, "latencies": [], "failures": []}

    if not args.threads:
        print(f"  {'-' * 78}\n  SINGLE QUESTIONS ({len(cases)})\n  {'-' * 78}")
        r = run_single(base_url, cases, allowed)
        for key in totals:
            totals[key] = totals[key] + r[key] if isinstance(r[key], (int, list)) else totals[key]

    if not args.single and not args.only:
        print(f"\n  {'-' * 78}\n  MULTI-TURN THREADS\n  {'-' * 78}")
        r = run_threads(base_url, data.get("threads", []), allowed)
        for key in totals:
            totals[key] = totals[key] + r[key] if isinstance(r[key], (int, list)) else totals[key]

    # ---------------------------------------------------------------- report
    lat = [x for x in totals["latencies"] if x > 0]
    total = totals["pass"] + totals["fail"]

    print(f"\n  {'=' * 78}")
    print(f"  RESULT: {totals['pass']}/{total} passed")
    if totals["blockers"]:
        print(f"  {RED}{totals['blockers']} GUARDRAIL BLOCKER(S) — do not demo until fixed{RESET}")

    if lat:
        lat_sorted = sorted(lat)
        p95 = lat_sorted[int(len(lat_sorted) * 0.95) - 1] if len(lat_sorted) > 1 else lat_sorted[0]
        print(f"\n  TIME TO FIRST WORD  (target: 1000-1500 ms)")
        print(f"    average : {statistics.mean(lat):7.0f} ms")
        print(f"    median  : {statistics.median(lat):7.0f} ms")
        print(f"    p95     : {p95:7.0f} ms")
        print(f"    fastest : {min(lat):7.0f} ms")
        print(f"    slowest : {max(lat):7.0f} ms")
        verdict = (
            f"{GREEN}meets the target{RESET}"
            if statistics.median(lat) <= 1500
            else f"{YELLOW}over target — check retrieval_top_k and the model{RESET}"
        )
        print(f"    verdict : {verdict}")

    if totals["failures"]:
        print(f"\n  {'-' * 78}\n  FAILURES IN DETAIL\n  {'-' * 78}")
        for case, problems, reply in totals["failures"][:20]:
            print(f"\n  #{case['id']} [{case.get('category', 'thread')}] {case['q']}")
            for p in problems:
                print(f"    ! {p}")
            print(f"    {DIM}reply: {reply[:200]}{RESET}")

    if args.save:
        Path(args.save).write_text(
            json.dumps(
                {
                    "url": base_url,
                    "passed": totals["pass"],
                    "failed": totals["fail"],
                    "blockers": totals["blockers"],
                    "latency_ms": {
                        "mean": round(statistics.mean(lat), 1) if lat else 0,
                        "median": round(statistics.median(lat), 1) if lat else 0,
                    },
                    "failures": [
                        {"id": str(c["id"]), "question": c["q"], "problems": p, "reply": r}
                        for c, p, r in totals["failures"]
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\n  saved to {args.save}")

    print()
    return 1 if totals["blockers"] else (0 if totals["fail"] == 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
