"""Strands tools. Read-only. Every fact they return comes from an official FDA label, with its section id."""
import re

from strands import tool

from . import lexicon, openfda

TAMIL = re.compile(r"[\u0B80-\u0BFF]")
DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def language_of(text):
    return "ta" if TAMIL.search(text or "") else "hi" if DEVANAGARI.search(text or "") else "en"


def has_tamil(text):
    return bool(TAMIL.search(text or ""))


def has_hindi(text):
    return bool(DEVANAGARI.search(text or ""))


def in_language(text, lang):
    """True if the text is written in the expected script."""
    if lang == "ta":
        return has_tamil(text)
    if lang == "hi":
        return has_hindi(text)
    return not has_tamil(text) and not has_hindi(text)


def guidance_ids():
    """Citation ids that really exist (the scorer checks every citation against this)."""
    return openfda.section_ids()


@tool
def read_label(medicine: str, section: str = "drug_interactions") -> dict:
    """Read one section of a medicine's official FDA label. Use it only to explain a fact already in FACTS.

    Args:
        medicine: generic or brand name, e.g. warfarin or Ecosprin
        section: one of drug_interactions, warnings, warnings_and_cautions, contraindications, boxed_warning,
                 ask_doctor_or_pharmacist, indications_and_usage
    """
    lab = openfda.label(medicine)
    if not lab:
        return {"found": False, "medicine": medicine}
    text = lab["sections"].get(section)
    if not text:
        return {"found": True, "medicine": lab["key"], "section": section, "text": None,
                "available": sorted(lab["sections"])}
    return {"found": True, "medicine": lab["key"], "cite": f"{lab['key']}:{section}", "text": " ".join(text.split())[:2500]}


@tool
def check_pair(medicine_a: str, medicine_b: str) -> dict:
    """Check whether either official label names the other medicine (or its drug class). Quotes the label.

    Args:
        medicine_a: first medicine
        medicine_b: second medicine
    """
    a, b = lexicon.normalize(medicine_a), lexicon.normalize(medicine_b)
    q = openfda.mentions(a, b) + openfda.mentions(b, a)
    return {"pair": [a, b], "labels_mention_each_other": bool(q), "quotes": q[:3]}
