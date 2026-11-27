r"""
Measures how good the SEARCH is, before the model ever sees anything.

    .\.venv\Scripts\python.exe -X utf8 backend\tests\retrieval_eval.py
    ...retrieval_eval.py --top-k 8          try a different cut-off
    ...retrieval_eval.py --no-write         print only, write no file

WHAT THIS IS, AND WHAT run_eval.py IS

    run_eval.py        asks the live server real questions and judges the ANSWER.
                       Needs the server running, costs ~70 model calls.
    retrieval_eval.py  asks only "did the search find the right page?".
                       No server, no model calls, one cheap embedding per
                       question. This is the number that actually explains why
                       an answer was good or bad.

  Q: Why measure search separately? The answers look fine.
  A: Because when an answer IS wrong, you cannot tell whose fault it was. If
     the right page was never retrieved, no prompt will fix it. If it WAS
     retrieved and the answer still went wrong, the prompt is the problem.
     One number tells you which half to work on.

WHAT IT REPORTS

    Hit@1   how often the top result came from a correct file
    Hit@4   how often a correct file was anywhere in the top 4 (what the bot sees)
    MRR     1 if the correct file was first, 0.5 if second, 0.33 if third...
            Rewards ranking, not just presence.
    Refused how many of the off-topic questions correctly found nothing

  Q: Why is Hit@4 the headline and not Hit@1?
  A: Because the bot is given 4 chunks, not 1. If the right page is third, the
     model still reads it and answers correctly. Hit@1 matters for ranking
     quality; Hit@4 matters for whether the answer can be right at all.

HONEST LIMITS OF THIS MEASUREMENT
  * It checks the FILE, not the paragraph. The right file with the wrong
    section still counts as a hit.
  * The labels are human opinion. They are only as good as the review in
    retrieval_cases.json.
  * 34 questions is small. A 3% change is noise, not an improvement.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_company, settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.db.database import dispose_engine, run, session_scope  # noqa: E402
from app.llm.embeddings import embed_query  # noqa: E402
from app.rag.vectorstore import count_documents, search  # noqa: E402

CASES_FILE = Path(__file__).resolve().parent / "retrieval_cases.json"
RESULTS_FILE = Path(__file__).resolve().parents[2] / "docs" / "RETRIEVAL_RESULTS.md"

GREEN, RED, YELLOW, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"


def _rank_of_expected(hits, expected: list[str]) -> int:
    """1-based position of the first hit from an acceptable file, or 0 for none."""
    for position, hit in enumerate(hits, start=1):
        if hit.source in expected:
            return position
    return 0


async def main() -> None:
    parser = argparse.ArgumentParser(description="Measure retrieval quality")
    parser.add_argument("--top-k", type=int, default=None, help="how many chunks to fetch")
    parser.add_argument("--no-write", action="store_true", help="do not write the results file")
    args = parser.parse_args()

    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases, negatives = data["cases"], data["negatives"]

    company = get_company()
    top_k = args.top_k or int(company.get("limits.retrieval_top_k", 4))
    floor = float(company.get("limits.retrieval_min_score", 0.28))

    print(f"\n  Retrieval eval — {len(cases)} questions, {len(negatives)} off-topic")
    print(f"  top_k={top_k}  min_score={floor}  model={settings.GEMINI_EMBED_MODEL}\n")

    session = await session_scope()
    try:
        chunks = await count_documents(session)
        if chunks == 0:
            raise SystemExit("  No chunks in the database. Run ingest.py first.")
        print(f"  {chunks} chunks in the database\n")

        rows, hit1, hit4, mrr_total, title_hits, title_total = [], 0, 0, 0.0, 0, 0
        times: list[int] = []

        for case in cases:
            started = time.perf_counter()
            vector = await embed_query(case["q"])
            hits = await search(session, vector, top_k=top_k)
            times.append(int((time.perf_counter() - started) * 1000))

            rank = _rank_of_expected(hits, case["expect"])
            if rank == 1:
                hit1 += 1
            if rank:
                hit4 += 1
                mrr_total += 1 / rank

            # Secondary, stricter check: was the right SECTION found, not just
            # the right file? Only counted where the case names a heading.
            hint = case.get("title_hint")
            if hint:
                title_total += 1
                if any(hint.lower() in (h.title or "").lower() for h in hits[:top_k]):
                    title_hits += 1

            mark = f"{GREEN}  1{RESET}" if rank == 1 else (f"{YELLOW}{rank:3}{RESET}" if rank else f"{RED}  -{RESET}")
            best = hits[0].score if hits else 0.0
            got = hits[0].source if hits else "(nothing)"
            print(f"  {mark}  {case['id']:8} {case['q'][:44]:46} {DIM}top={got} {best:.3f}{RESET}")
            rows.append({"id": case["id"], "q": case["q"], "expect": case["expect"],
                         "rank": rank, "top": got, "score": round(best, 3)})

        # --- the off-topic questions: finding NOTHING is the correct answer ---
        print()
        refused = 0
        neg_rows = []
        for case in negatives:
            vector = await embed_query(case["q"])
            hits = await search(session, vector, top_k=top_k)
            best = hits[0].score if hits else 0.0
            ok = best < floor
            refused += ok
            mark = f"{GREEN} ok{RESET}" if ok else f"{RED}  !{RESET}"
            print(f"  {mark}  {case['id']:8} {case['q'][:44]:46} {DIM}best={best:.3f}{RESET}")
            neg_rows.append({"id": case["id"], "q": case["q"], "score": round(best, 3), "refused": ok})
    finally:
        await session.close()
        await dispose_engine()

    n = len(cases)
    summary = {
        "hit1": round(100 * hit1 / n, 1),
        "hit4": round(100 * hit4 / n, 1),
        "mrr": round(mrr_total / n, 3),
        "section": round(100 * title_hits / title_total, 1) if title_total else 0.0,
        "refused": round(100 * refused / len(negatives), 1),
        "median_ms": sorted(times)[len(times) // 2],
        "chunks": chunks,
        "top_k": top_k,
        "floor": floor,
    }

    print(f"\n  {'=' * 58}")
    print(f"  Hit@1              {summary['hit1']:5.1f}%   right file ranked first")
    print(f"  Hit@{top_k}              {summary['hit4']:5.1f}%   right file somewhere in the top {top_k}")
    print(f"  MRR                {summary['mrr']:5.3f}    ranking quality, 1.000 is perfect")
    print(f"  Right section      {summary['section']:5.1f}%   stricter: the named heading was found")
    print(f"  Off-topic refused  {summary['refused']:5.1f}%   correctly found nothing")
    print(f"  Median search      {summary['median_ms']:5}ms")
    print(f"  {'=' * 58}\n")

    if not args.no_write:
        _write_results(summary, rows, neg_rows)
        print(f"  Written to {RESULTS_FILE}\n")

    # A missed off-topic question means the bot would answer something it has
    # no business answering. That is a correctness failure, so exit non-zero.
    if refused < len(negatives):
        raise SystemExit(f"  {len(negatives) - refused} off-topic question(s) were NOT refused.")


def _write_results(summary: dict, rows: list[dict], neg_rows: list[dict]) -> None:
    misses = [r for r in rows if r["rank"] == 0]
    not_first = [r for r in rows if r["rank"] > 1]
    when = time.strftime("%d %b %Y")

    lines = [
        "# Retrieval results",
        "",
        "Generated by `backend/tests/retrieval_eval.py`. Do not edit by hand.",
        f"Last run: {when}",
        "",
        "This measures the SEARCH, not the answers. It asks one question only:",
        "when a visitor asks something, does the search hand the model the right",
        "page? If it does not, no amount of prompt wording can save the answer.",
        "",
        "## Numbers",
        "",
        "| Measure | Result | What it means |",
        "|---|---|---|",
        f"| Hit@1 | **{summary['hit1']}%** | The right file was ranked first |",
        f"| Hit@{summary['top_k']} | **{summary['hit4']}%** | The right file was among the {summary['top_k']} the model reads |",
        f"| MRR | **{summary['mrr']}** | Ranking quality. 1.000 means always first |",
        f"| Right section | {summary['section']}% | Stricter: the exact heading was retrieved |",
        f"| Off-topic refused | {summary['refused']}% | Questions it correctly would not answer |",
        f"| Median search time | {summary['median_ms']} ms | Embedding plus database lookup |",
        "",
        f"Run over {len(rows)} labelled questions and {len(neg_rows)} off-topic ones, "
        f"against {summary['chunks']} chunks, `top_k={summary['top_k']}`, "
        f"score floor `{summary['floor']}`.",
        "",
        "## How to read this",
        "",
        f"**Hit@{summary['top_k']} is the number that matters.** The model is given "
        f"{summary['top_k']} chunks, so a correct page in third place is still read and "
        "still produces a correct answer. Hit@1 and MRR describe ranking quality, which "
        "matters for cost and for crowding out the right page when content grows.",
        "",
        "**Off-topic refused should stay at 100%.** A system that always retrieves "
        "something is not more helpful, it is less honest. These five questions have no "
        "answer in the content, so the correct behaviour is to find nothing and say so.",
        "",
    ]

    if misses:
        lines += ["## Questions where the right page was never found", "",
                  "| Question | Should have found | Actually top | Score |", "|---|---|---|---|"]
        lines += [f"| {r['q']} | {', '.join(r['expect'])} | {r['top']} | {r['score']} |" for r in misses]
        lines += [""]
    else:
        lines += ["## Misses", "", "None. Every question found an acceptable page.", ""]

    if not_first:
        lines += ["## Found, but not ranked first", "",
                  "| Question | Position | Top result instead |", "|---|---|---|"]
        lines += [f"| {r['q']} | {r['rank']} | {r['top']} |" for r in not_first]
        lines += [""]

    lines += [
        "## What this does not measure",
        "",
        "- It checks the **file**, not the paragraph. The right file with the wrong",
        "  section still counts as a hit. The 'right section' row is the stricter view.",
        "- The labels are human judgement, written in `retrieval_cases.json` and",
        "  reviewed by hand. They are only as good as that review.",
        f"- {len(rows)} questions is a small set. Treat a change under about 3% as noise.",
        "- It says nothing about whether the final answer was well written. That is",
        "  `run_eval.py`.",
        "",
    ]

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    setup_logging()
    run(main())
