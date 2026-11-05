"""Official US FDA drug labels from openFDA (https://open.fda.gov/apis/drug/label/), cached on disk.

The cache in agent/data/labels/ is committed so a run is reproducible and works offline. Each file keeps the
label's set_id, effective_time and the date we fetched it. Delete a file to refresh it.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import lexicon

CACHE = Path(__file__).parent / "data" / "labels"
API = "https://api.fda.gov/drug/label.json"
SECTIONS = ["boxed_warning", "contraindications", "drug_interactions", "warnings_and_cautions", "warnings", "precautions",
            "ask_doctor_or_pharmacist", "do_not_use", "stop_use", "indications_and_usage", "purpose"]
# sections searched for interactions, most specific first
INTERACTION_SECTIONS = ["drug_interactions", "contraindications", "boxed_warning", "warnings_and_cautions", "warnings",
                        "precautions", "ask_doctor_or_pharmacist", "do_not_use"]
_lock = threading.Lock()
_mem: dict[str, dict | None] = {}


def _slug(key):
    return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


def _get(search: str, limit: int = 10) -> list[dict]:
    url = f"{API}?search={urllib.parse.quote(search, safe=':+')}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode("utf-8")).get("results", [])
    except urllib.error.HTTPError as e:
        if e.code == 404:  # openFDA answers 404 when nothing matches
            return []
        raise


def _pick(results: list[dict], want: str) -> dict | None:
    """Prefer a single-ingredient label whose generic name matches, with interaction text."""
    best = None
    for x in results:
        gn = " ".join(x.get("openfda", {}).get("generic_name", [])).lower()
        bn = " ".join(x.get("openfda", {}).get("brand_name", [])).lower()
        if want not in gn and want not in bn:
            continue
        single = "," not in gn and " and " not in gn
        has_ix = any(k in x for k in ("drug_interactions", "ask_doctor_or_pharmacist"))
        score = 2 * has_ix + single + (gn.strip() == want)
        if best is None or score > best[0]:
            best = (score, x)
    return best[1] if best else None


def label(key: str) -> dict | None:
    """The label for one medicine (generic key or any name), or None if openFDA has no label for it."""
    key = lexicon.normalize(key)
    with _lock:
        if key in _mem:
            return _mem[key]
    path = CACHE / f"{_slug(key)}.json"
    if path.exists():
        lab = json.loads(path.read_text(encoding="utf-8"))
    else:
        fda = lexicon.KNOWN.get(key, {}).get("fda")
        want = key.lower()
        tries = ([f'openfda.generic_name.exact:"{fda}"'] if fda else []) + \
                [f'openfda.generic_name:"{key}"', f'openfda.brand_name:"{key}"']
        x = None
        for q in tries:
            x = _pick(_get(q), (fda or key).lower() if q.endswith(f'"{fda}"') else want)
            if x:
                break
        if x is None:
            lab = {"key": key, "found": False, "fetched_on": dt.date.today().isoformat()}
        else:
            lab = {"key": key, "found": True, "generic_name": x.get("openfda", {}).get("generic_name", []),
                   "brand_name": x.get("openfda", {}).get("brand_name", [])[:5], "set_id": x.get("set_id"),
                   "effective_time": x.get("effective_time"), "fetched_on": dt.date.today().isoformat(),
                   "url": f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={x.get('set_id')}",
                   "sections": {k: " ".join(x[k]) for k in SECTIONS if k in x}}
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(lab, ensure_ascii=False, indent=1), encoding="utf-8")
    lab = lab if lab.get("found") else None
    with _lock:
        _mem[key] = lab
    return lab


def section_ids() -> set[str]:
    """Every citation id that exists in the labels loaded so far: '<medicine>:<section>'."""
    with _lock:
        labs = [v for v in _mem.values() if v]
    return {f"{l['key']}:{s}" for l in labs for s in l["sections"]}


def _clean(s):
    return " ".join((s or "").split())


def _snippet(text, start, end, width=170):
    a, b = max(0, start - width), min(len(text), end + width)
    if a > 0:
        sp = text.find(" ", a)
        a = sp + 1 if 0 <= sp < start else a
    if b < len(text):
        sp = text.rfind(" ", end, b)
        b = sp if sp > end else b
    return ("..." if a else "") + _clean(text[a:b]) + ("..." if b < len(text) else "")


def mentions(a: str, b: str, limit: int = 2) -> list[dict]:
    """Places where medicine a's label names medicine b (or b's class). Quoted, with the section id."""
    lab = label(a)
    if not lab:
        return []
    out, seen = [], set()
    for sec in INTERACTION_SECTIONS:
        text = lab["sections"].get(sec)
        if not text:
            continue
        for term in lexicon.terms_for(lexicon.normalize(b)):
            m = re.search(r"(?<![\w-])" + re.escape(term) + r"s?(?![\w])", text, re.I)
            if m and sec not in seen:
                seen.add(sec)
                out.append({"label_of": lab["key"], "section": sec, "matched": term, "cite": f"{lab['key']}:{sec}",
                            "quote": _snippet(text, m.start(), m.end())})
                break
        if len(out) >= limit:
            break
    return out


def interactions(found: list[str], named: list[str] | None = None) -> list[dict]:
    """Every pair whose labels name each other. Code decides; the model only explains what is returned.

    found: medicines with a label. named: every medicine the person named; a label can warn about a medicine
    even when that medicine has no label of its own (e.g. levothyroxine's label names calcium carbonate)."""
    flags, seen = [], set()
    found = list(dict.fromkeys(found))
    for a in found:
        for b in dict.fromkeys(list(named or []) + found):
            pair = frozenset((a, b))
            if a == b or pair in seen:
                continue
            seen.add(pair)
            q = mentions(a, b) + (mentions(b, a) if b in found else [])
            if q:
                flags.append({"drugs": [a, b], "quotes": q[:3]})
    return flags


def purpose(key: str, n: int = 260) -> str:
    lab = label(key)
    if not lab:
        return ""
    s = lab["sections"]
    return _clean(s.get("indications_and_usage") or s.get("purpose") or "")[:n]
