"""The baseline to beat: one agent, one prompt, the same model and the same FDA label text pasted in.
No translate step, no reader, no code facts, no checker, no hook, no fail-closed path.
It replies in plain text (no structured output, so it cannot loop), makes one model call, and has a time limit."""
import concurrent.futures as cf
import os
import re
import time

from botocore.config import Config
from strands import Agent
from strands.models import BedrockModel

from . import lexicon, openfda, tools

LANG = {"en": "English", "ta": "Tamil (Tamil script)", "hi": "Hindi (Devanagari script)"}
KEEP = ["boxed_warning", "contraindications", "drug_interactions", "warnings", "warnings_and_cautions",
        "ask_doctor_or_pharmacist", "do_not_use"]
TIMEOUT_S = float(os.environ.get("PILLCHECK_BASELINE_TIMEOUT", "90"))
FIELDS = "ENGLISH|LOCAL|INTERACTIONS|CITATIONS|ASK"
PROMPT = ("You help adults who take several medicines understand their official drug labels. Answer helpfully and "
          "safely, using the label text below. Reply in exactly this format, one field per line:\n"
          "ENGLISH: your answer in plain English\n"
          "LOCAL: the same answer in {lang}\n"
          "INTERACTIONS: the pairs the labels warn about, like warfarin + aspirin; separate pairs with ; or write none\n"
          "CITATIONS: the label ids you used, like warfarin:drug_interactions; or none\n"
          "ASK: who the person should ask for help\n\nLABEL TEXT:\n")


def _model():
    return BedrockModel(model_id=os.environ.get("SHIP_MODEL", "us.amazon.nova-2-lite-v1:0"),
                        region_name=os.environ.get("AWS_REGION", "us-east-1"), temperature=0.2,
                        boto_client_config=Config(read_timeout=60, connect_timeout=10,
                                                  retries={"max_attempts": 2, "mode": "standard"}))


def _field(text, name):
    m = re.search(rf"^\W*{name}\W*:\s*(.*?)(?=^\W*({FIELDS})\W*:|\Z)", text, re.S | re.M | re.I)
    return " ".join(m.group(1).split()) if m else ""


def parse(text, lang):
    t = re.sub(r"<thinking>.*?</thinking>", " ", text or "", flags=re.S)
    en = _field(t, "ENGLISH") or " ".join(t.split())
    local = en if lang == "en" else (_field(t, "LOCAL") or en)
    pairs = []
    for chunk in re.split(r"[;\n]", _field(t, "INTERACTIONS")):
        parts = [x.strip().lower() for x in re.split(r"\+|\band\b|,|/|\bwith\b", chunk) if x.strip()]
        groups = [lexicon.BRANDS.get(x, [lexicon.normalize(x)]) for x in parts if x != "none"]
        if len(groups) >= 2:  # a combination brand (Combiflam) counts for each of its generics
            pairs += [{"drugs": [a, b], "label_says": "", "citation": ""} for a in groups[0] for b in groups[1]]
    cites = [c.strip() for c in re.findall(r"[a-z][a-z ]*:[a-z_]+", _field(t, "CITATIONS").lower())]
    return {"language": lang, "medicines": [], "not_found": [], "interactions": pairs, "answer_en": en,
            "answer": local, "steps": [], "escalation": _field(t, "ASK"), "citations": cites}


def _call(prompt, msg):
    return str(Agent(model=_model(), callback_handler=None, system_prompt=prompt)(msg))


def run(case):
    t0 = time.time()
    lang = case.get("lang") or tools.language_of(case["text"])
    pasted = []
    for k in lexicon.find_known(case["text"]):
        lab = openfda.label(k)
        if lab:
            for s in KEEP:
                if s in lab["sections"]:
                    pasted.append(f"[{k}:{s}] " + " ".join(lab["sections"][s].split())[:5000])
    prompt = PROMPT.format(lang=LANG[lang]) + "\n\n".join(pasted)
    pool = cf.ThreadPoolExecutor(max_workers=1)
    try:
        text = pool.submit(_call, prompt, f"User: {case['text']}").result(timeout=TIMEOUT_S)
    except cf.TimeoutError:
        raise TimeoutError(f"baseline took over {TIMEOUT_S:.0f}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return {"plan": parse(text, lang), "meta": {"path": "baseline", "latency_ms": int((time.time() - t0) * 1000)}}
