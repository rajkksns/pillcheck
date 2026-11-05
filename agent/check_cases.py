"""Check cases.jsonl against the real FDA labels BEFORE you sign the cases off. No Bedrock calls.

    python -m agent.check_cases

For every case: the red flag code sees, the medicines it finds, and the pairs the labels link, next to what the
case expects. Fix a case (or the lexicon) where they disagree and you, a person, decide which one is right.
"""
import json
from pathlib import Path

from . import lexicon, openfda, safety


def main():
    bad = 0
    for line in Path("cases.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        exp = c["expected"]
        kind, hits = safety.red_flag(c["text"])
        keys = lexicon.find_known(c["text"])
        found = [k for k in keys if openfda.label(k)]
        got = [set(f["drugs"]) for f in openfda.interactions(found, keys)]
        want = [set(lexicon.normalize(x) for x in p) for p in exp.get("flags", [])]
        problems = []
        if (exp["escalation"] == "emergency") != bool(kind):
            problems.append(f"red flag {kind or 'none'} but expected {exp['escalation']}")
        if exp["escalation"] == "none":
            problems += [f"labels do not link {sorted(w)}" for w in want if w not in got]
            problems += [f"labels also link {sorted(g)} (add it to flags if right)" for g in got if g not in want]
        bad += bool(problems)
        print(f"{c['id']:6s} {'OK ' if not problems else 'FIX'} meds={found} flag={kind} " + "; ".join(problems))
    print(f"\n{bad} case(s) to look at. Labels cached in agent/data/labels/.")


if __name__ == "__main__":
    main()
