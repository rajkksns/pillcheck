"""Fix the labels in results/MEASURE.md for PillCheck and add how each answer was produced.

    python -m agent.report

The kit's table header says "HeatSafe Shift" and its last row says "failed closed" for every checker REVISE.
In PillCheck the code checks decide what ships, so this counts the real paths from results/raw_agent.jsonl.
"""
import collections
import json
from pathlib import Path

OUT = Path("results")


def main():
    md = (OUT / "MEASURE.md").read_text(encoding="utf-8")
    md = md.replace("| Metric | HeatSafe Shift |", "| Metric | PillCheck |")
    md = md.replace("Critic passed within 2 tries (else fixed text shipped)", "LLM checker said PASS within 2 tries (advisory)")
    rows = [json.loads(l) for l in (OUT / "raw_agent.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    paths = collections.Counter((r.get("output") or {}).get("meta", {}).get("path", "crashed") for r in rows)
    names = {"agent": "model explanation, passed code checks", "fixed": "code-written answer (model draft failed a code check)",
             "handoff": "red flag: fixed hand-off, no model", "no_pairs": "labels do not link the pair: code answer, no model",
             "not_found": "no official label: no guess", "no_medicine": "no medicine named", "crashed": "crashed"}
    table = ["", "## How each answer was produced", "", "| Path | Cases |", "|---|---|"]
    table += [f"| {names.get(k, k)} | {v} |" for k, v in paths.most_common()]
    marker = "\n## By language"
    if "## How each answer was produced" not in md:
        md = md.replace(marker, "\n".join(table) + "\n" + marker, 1)
    (OUT / "MEASURE.md").write_text(md, encoding="utf-8")
    print("\n".join(table))


if __name__ == "__main__":
    main()
