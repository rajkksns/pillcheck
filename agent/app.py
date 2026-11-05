"""PillCheck: what the official labels say about the medicines you take together. English, Tamil, Hindi.

    python -m agent.app "I take warfarin. Can I also take Ecosprin?"
    python -m agent.app "நான் warfarin எடுக்கிறேன். Combiflam சாப்பிடலாமா?" --json

Who decides what:
  code    red flags (emergency, self-harm, dose change) -> fixed reply, no model sees the message
  code    which medicines were named, their FDA labels, which pairs the labels link (quoted, with section ids)
  model   reader: lists medicine names the user typed (code then verifies each one on openFDA)
  model   explainer -> checker graph: plain-English explanation of the code's facts, checked, max 2 tries
  code    final checks: every flagged pair explained, no dosing advice, no "safe together", valid citations;
          if any fails, a fixed code-written answer ships instead (fail closed)
  AWS     Amazon Translate turns Tamil/Hindi into English on the way in and back on the way out
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import logging
import os
import re
import sys
import time

from strands import Agent
from strands.hooks import BeforeModelCallEvent, BeforeNodeCallEvent, HookProvider, HookRegistry
from strands.interventions import Deny, InterventionHandler, Proceed
from strands.models import BedrockModel
from strands.multiagent import GraphBuilder

from . import lexicon, openfda, safety, tools
from .plan import Answer, Explanation, Flag, Medicines
from .translate import translate

MODEL_ID = os.environ.get("SHIP_MODEL", "us.amazon.nova-2-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
NODE_TIMEOUT_S = float(os.environ.get("PILLCHECK_NODE_TIMEOUT", "45"))
GRAPH_TIMEOUT_S = float(os.environ.get("PILLCHECK_GRAPH_TIMEOUT", "100"))
if os.environ.get("PILLCHECK_DEBUG"):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", stream=sys.stderr)
    logging.getLogger("strands").setLevel(logging.DEBUG)
else:
    logging.getLogger("strands").setLevel(logging.CRITICAL)

READER = ("List every medicine name in the user's message exactly as written, including brands, Ayurvedic or "
          "unknown names. Do not add medicines that are not in the message. If there are none, return an empty list.")
EXPLAINER = ("You explain medicine labels to an adult who takes several medicines and has little health knowledge. "
             "Use ONLY the FACTS block. For each INTERACTION, say in one or two short sentences what the label warns "
             "about, naming both medicines. For a pair with no interaction in FACTS, say the labels do not name each "
             "other and that this does not prove they are safe together. Never say a combination is safe. Never give "
             "a dose, milligrams, timing, or advice to start, stop, skip or change a medicine. Plain English, at most "
             "120 words. If the user used a brand name, name the generic too, e.g. Combiflam (ibuprofen and acetaminophen). "
             "Reply with the explanation as plain text only: no lists, no headings, no JSON. Every fact you "
             "need is already in FACTS, so call read_label or check_pair only if a fact is truly missing. "
             "If the message contains checker problems, rewrite the explanation to fix every one.")
CHECKER = ("You review a draft explanation against the FACTS block. Answer only these three questions about the "
           "DRAFT, not about the medicines:\n"
           "1. Does the draft say a combination IS safe? A sentence saying the labels do not prove it is safe is "
           "the required warning, so it is NOT a problem.\n"
           "2. Does the draft name a medicine or a warning that is not in FACTS? A brand listed under NAMES THE USER "
           "USED is the same medicine as its generics, so it is NOT a problem.\n"
           "3. Does the draft give a number of mg, a number of tablets, a time to take a medicine, or tell the person "
           "to start, stop, skip or change one? Giving NO dose is required and is NEVER a problem.\n"
           "Missing detail from the label is NOT a problem: the label quotes are shown to the person separately. "
           "Do not call any tool. Reply on the first line with exactly PASS if the answer to all three is no. "
           "Otherwise reply REVISE, then one line per question answered yes.")


def verdict(text: str) -> tuple[bool, list[str]]:
    """Parse the checker's plain-text reply. Anything that is not a clear PASS counts as a problem."""
    lines = [l.strip(" -*") for l in _clean_text_lines(text) if l.strip(" -*")]
    if lines and lines[0].upper().startswith("PASS"):
        return True, []
    return False, (lines[1:] if lines and lines[0].upper().startswith("REVISE") else lines)[:4] or ["no verdict"]


def _clean_text_lines(t: str) -> list[str]:
    t = re.sub(r"<thinking>.*?</thinking>", " ", t or "", flags=re.S)
    return [l for l in t.splitlines() if l.strip()]


def say(tag, text):
    print(f"[{tag}] {text}", flush=True)  # evidence lines; `ss video` turns them into badges


def _model():
    return BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2)


class RedFlagGate:
    """The red-flag decision is plain code (safety.red_flag). Two Strands hooks enforce it at fixed moments:
    before any model call of the reader agent, and before any node of the explainer graph."""

    def __init__(self, *texts):
        self.kind, self.tripped = safety.red_flag(*texts)
        gate = self

        class _Agent(HookProvider):
            def register_hooks(self, registry: HookRegistry, **_):
                registry.add_callback(BeforeModelCallEvent, gate._model)

        class _Graph(HookProvider):
            def register_hooks(self, registry: HookRegistry, **_):
                registry.add_callback(BeforeNodeCallEvent, gate._node)

        self.agent_hook, self.graph_hook = _Agent(), _Graph()

    def _model(self, event: BeforeModelCallEvent):
        if self.tripped:
            event.cancel = f"red flag ({self.kind}): fixed reply"

    def _node(self, event: BeforeNodeCallEvent):
        if self.tripped:
            event.cancel_node = f"red flag ({self.kind}): fixed reply"


class OnlyTheirMedicines(InterventionHandler):
    """The explainer may read labels only for this person's medicines, and only a few times: the facts are
    already in FACTS, so a model that keeps calling tools is told to write the answer instead."""
    name = "only-their-medicines"
    MAX_CALLS = 2
    OUTPUT_TOOLS = {"Explanation", "Critique", "Medicines", "Answer"}  # Strands structured output is a tool too

    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.calls = 0

    def before_tool_call(self, event):
        args = event.tool_use.get("input", {})
        name = event.tool_use.get("name", "?")
        if name in self.OUTPUT_TOOLS:
            return Proceed()
        self.calls += 1
        say("tool", f"{name} {json.dumps(args, ensure_ascii=False)[:120]} (call {self.calls})")
        if self.calls > self.MAX_CALLS:
            say("guard", f"DENY {name}: tool budget of {self.MAX_CALLS} used, write the explanation now")
            return Deny(reason="You already have every fact in FACTS. Do not call tools again. Write the explanation now.")
        named = [lexicon.normalize(v) for k, v in args.items() if k.startswith("medicine")]
        extra = [n for n in named if n not in self.allowed]
        if extra:
            say("guard", f"DENY label read for {extra}: not one of this person's medicines")
            return Deny(reason=f"Only these medicines may be read: {sorted(self.allowed)}.")
        return Proceed()


def facts_block(found, flags, user_text=""):
    lines = ["FACTS (from official US FDA labels via openFDA; quote, do not add):"]
    t = (user_text or "").lower()
    names = [f"- {b.capitalize()} = {' + '.join(gs)}" for b, gs in lexicon.BRANDS.items() if lexicon._has(t, b)]
    if names:
        lines += ["NAMES THE USER USED (a brand is the same medicine as its generic names, not a new medicine):"] + names
    lines.append("MEDICINES:")
    for k in found:
        lab = openfda.label(k)
        lines.append(f"- {k} (label effective {lab.get('effective_time')}): used for: {openfda.purpose(k)}")
    lines.append("INTERACTIONS:" if flags else "INTERACTIONS: none of these labels name each other.")
    for f in flags:
        for q in f["quotes"]:
            lines.append(f"- {f['drugs'][0]} + {f['drugs'][1]} [{q['cite']}] the {q['label_of']} label says: \"{q['quote']}\"")
    lines.append("VALID CITATION IDS: " + ", ".join(sorted({q['cite'] for f in flags for q in f['quotes']} |
                                                            {f"{k}:indications_and_usage" for k in found})))
    return "\n".join(lines)


def build_graph(gate, allowed):
    explainer = Agent(model=_model(), name="explainer", system_prompt=EXPLAINER, tools=[tools.read_label, tools.check_pair],
                      interventions=[OnlyTheirMedicines(allowed)], callback_handler=None)
    checker = Agent(model=_model(), name="checker", system_prompt=CHECKER, callback_handler=None)

    printed = set()

    def again(state):
        r = state.results.get("checker")
        if not r:
            return False
        ok, probs = verdict(str(r.result))
        n = sum(1 for x in state.execution_order if x.node_id == "explainer")
        if n not in printed:
            printed.add(n)
            say("critic", f"pass {n}: " + ("PASS" if ok else "REVISE - " + "; ".join(probs)[:200]))
        return not ok and n < 2

    b = GraphBuilder()
    b.add_node(explainer, "explainer")
    b.add_node(checker, "checker")
    b.add_edge("explainer", "checker")
    b.add_edge("checker", "explainer", condition=again)
    b.set_entry_point("explainer")
    b.set_max_node_executions(4)
    b.reset_on_revisit(True)
    b.set_hook_providers([gate.graph_hook])
    if hasattr(b, "set_node_timeout"):
        b.set_node_timeout(NODE_TIMEOUT_S)
    if hasattr(b, "set_execution_timeout"):
        b.set_execution_timeout(GRAPH_TIMEOUT_S)
    return b.build()


def _mentioned(text, drug):
    t = text.lower()
    return any(term in t for term in lexicon.terms_for(drug)[:1] + [drug]) or any(
        b in t for b, gs in lexicon.BRANDS.items() if drug in gs)


def _clean_text(t: str) -> str:
    t = re.sub(r"<thinking>.*?</thinking>", " ", t or "", flags=re.S)
    return " ".join(t.split())


def final_checks(exp: Explanation, flags, allowed=()) -> list[str]:
    """Deterministic checks on the model's words. These decide what ships; any problem -> the fixed answer."""
    text = exp.answer_en + " " + " ".join(exp.steps)
    extra = [m for m in lexicon.find_known(exp.answer_en) if allowed and m not in allowed]
    if extra:
        return [f"names a medicine the person did not mention: {', '.join(extra)}"]
    problems = [f"dosing advice: {s}" for s in safety.dosing_advice(text)]
    problems += [f"safety claim: {s}" for s in safety.safety_claims(text)]
    for f in flags:
        if not all(_mentioned(exp.answer_en, d) for d in f["drugs"]):
            problems.append(f"interaction not explained: {' + '.join(f['drugs'])}")
    return problems


def fixed_answer(found, flags, not_found=()) -> str:
    """Written by code from the label quotes alone: no model words. Used when there is nothing for a model to
    explain, or when the model's explanation fails any check."""
    if not flags:
        if len(found) == 1:
            return (f"The official {found[0]} label does not name your other medicine. That does not prove they are "
                    "safe together.") if not_found else f"I found the official {found[0]} label."
        return (f"The official labels of {', '.join(found)} do not name each other. "
                "That does not prove they are safe together.")
    parts = ["Your medicine labels have a warning about taking some of them together."]
    for f in flags:
        q = f["quotes"][0]
        other = f["drugs"][1] if q["label_of"] == f["drugs"][0] else f["drugs"][0]
        sec = q["section"].replace("_", " ")
        parts.append(f"The {q['label_of']} label names {other} in its {sec} section.")
    parts.append("The label's own words are shown below.")
    return " ".join(parts)


def _out(lang, answer_en, steps_en, meta, found=(), not_found=(), flags=(), citations=(), local=None, steps_local=None):
    tr_ok = True
    if local is None:
        bits = []
        for sent in re.split(r"(?<=[.!?])\s+", answer_en):
            t, ok = translate(sent, "en", lang)
            bits.append(t)
            tr_ok = tr_ok and ok
        local = " ".join(bits)
    if steps_local is None:
        steps_local = []
        for s in steps_en:
            t, ok = translate(s, "en", lang)
            steps_local.append(t)
            tr_ok = tr_ok and ok
    meta["translate_ok"] = meta.get("translate_ok", True) and tr_ok
    ix = [Flag(drugs=f["drugs"], label_says=q["quote"], citation=q["cite"]) for f in flags for q in f["quotes"][:1]]
    ans = Answer(language=lang, medicines=list(found), not_found=list(not_found), interactions=ix, answer_en=answer_en,
                 answer=local, steps=steps_local, escalation=safety.PHARMACIST[lang], citations=list(citations))
    return {"plan": ans.model_dump(), "meta": meta}


def run(case: dict) -> dict:
    t0 = time.time()
    text = case["text"]
    lang = case.get("lang") or tools.language_of(text)
    text_en, ok = translate(text, lang, "en")
    meta = {"path": "agent", "passes": 0, "critic_ok": None, "translate_ok": ok, "red_flag": None}
    gate = RedFlagGate(text, text_en)

    # 1. reader (a model) lists names; the gate cancels it before the model is called on a red flag
    names = []
    try:
        r = Agent(model=_model(), name="reader", system_prompt=READER, hooks=[gate.agent_hook],
                  structured_output_model=Medicines, callback_handler=None)(text_en)
        names = list(getattr(r, "structured_output", None).names) if not gate.tripped else []
    except Exception:
        if not gate.tripped:
            names = []  # reader failed: fall back to the code's own name list below
    if gate.tripped:
        say("safety", f"RED FLAG {gate.kind} ({', '.join(gate.tripped)}) -> no model answer, fixed reply")
        meta.update(path="handoff", red_flag=gate.kind, latency_ms=int((time.time() - t0) * 1000))
        h = safety.HANDOFF[gate.kind]
        return _out(lang, h["en"], [], meta, local=h[lang], steps_local=[])

    # 2. code verifies every name on openFDA and finds which labels name each other
    keys = list(dict.fromkeys(lexicon.find_known(text + " " + text_en) + [lexicon.normalize(n) for n in names if n.strip()]))
    found = [k for k in keys if openfda.label(k)]
    not_found = [k for k in keys if k not in found]
    flags = openfda.interactions(found, keys)
    say("labels", f"found {found or 'none'} | no label {not_found or 'none'} | {len(flags)} pair(s) linked by the labels")
    prefix = safety.NOT_FOUND["en"].format(names=", ".join(not_found)) if not_found else ""

    if not keys:
        meta.update(path="no_medicine", latency_ms=int((time.time() - t0) * 1000))
        return _out(lang, safety.NO_MEDICINE["en"], [], meta, local=safety.NO_MEDICINE[lang], steps_local=[])
    if not found:
        meta.update(path="not_found", latency_ms=int((time.time() - t0) * 1000))
        return _out(lang, prefix, [], meta, not_found=not_found,
                    local=safety.NOT_FOUND[lang].format(names=", ".join(not_found)), steps_local=[])

    if not flags:
        meta.update(path="no_pairs", latency_ms=int((time.time() - t0) * 1000))
        answer_en = (prefix + " " + fixed_answer(found, flags, not_found)).strip()
        say("plan", f"no_pairs | code answer, no model | {meta['latency_ms']} ms")
        return _out(lang, answer_en, list(safety.STEPS_EN), meta, found, not_found, flags,
                    [f"{k}:indications_and_usage" for k in found])

    # 3. explainer -> checker graph writes the plain-English explanation of the code's facts
    facts = facts_block(found, flags, text + " " + text_en)
    exp, problems = None, ["no explanation"]
    try:
        say("graph", "explainer -> checker started")
        pool = cf.ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(build_graph(gate, found), f"User question: {text_en}\n\n{facts}")
        try:
            res = fut.result(timeout=GRAPH_TIMEOUT_S + 20)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        say("graph", f"done: {[n.node_id for n in res.execution_order]}")
        text_out = _clean_text(str(res.results["explainer"].result))
        exp = Explanation(answer_en=text_out, steps=list(safety.STEPS_EN), citations=[]) if text_out else None
        crit = res.results.get("checker")
        meta["critic_ok"] = bool(crit) and verdict(str(crit.result))[0]
        meta["passes"] = sum(1 for n in res.execution_order if n.node_id == "explainer")
        problems = final_checks(exp, flags, set(keys)) if exp else ["no explanation"]
    except Exception as e:
        problems = [f"graph failed: {type(e).__name__}: {str(e)[:120]}"]
    if not problems and not meta["critic_ok"]:
        say("safety", "checker still asked for changes; code checks passed, so the explanation ships")

    valid = openfda.section_ids()
    if problems:
        say("safety", "FAIL CLOSED -> fixed answer from label quotes: " + "; ".join(problems)[:200])
        meta["path"] = "fixed"
        answer_en, steps, cites = fixed_answer(found, flags), list(safety.STEPS_EN), sorted({q["cite"] for f in flags for q in f["quotes"]})
    else:
        answer_en, steps = exp.answer_en, exp.steps
        cites = sorted({q["cite"] for f in flags for q in f["quotes"]} & valid) or [f"{k}:indications_and_usage" for k in found]
    answer_en = (prefix + " " + answer_en).strip()
    meta["latency_ms"] = int((time.time() - t0) * 1000)
    say("plan", f"{meta['path']} | {len(flags)} interaction(s) | {meta['latency_ms']} ms")
    return _out(lang, answer_en, steps, meta, found, not_found, flags, cites)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m agent.app")
    ap.add_argument("text")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = run({"text": a.text})
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        p = out["plan"]
        print("\n" + p["answer"])
        for f in p["interactions"]:
            print(f"\n  [{f['citation']}] \"{f['label_says'][:300]}\"")
        print("\n" + p["escalation"])
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
