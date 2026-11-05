"""Medicine names. Code owns this list; the model never maps a brand to a generic.

KNOWN: generic key -> openFDA generic name (exact) + words that mean this drug or its class inside another label.
BRANDS: common Indian brand names -> generic keys. Reviewed against the strip, but get a pharmacist to check before relying on it.
"""
import re

KNOWN = {
    "warfarin":          {"fda": "WARFARIN SODIUM",           "terms": ["warfarin", "anticoagulant", "coumarin", "blood thinning"]},
    "aspirin":           {"fda": "ASPIRIN",                   "terms": ["aspirin", "salicylate", "nsaid", "antiplatelet", "nonsteroidal anti-inflammatory"]},
    "ibuprofen":         {"fda": "IBUPROFEN",                 "terms": ["ibuprofen", "nsaid", "nonsteroidal anti-inflammatory", "non-steroidal anti-inflammatory"]},
    "acetaminophen":     {"fda": "ACETAMINOPHEN",             "terms": ["acetaminophen", "paracetamol"]},
    "clopidogrel":       {"fda": "CLOPIDOGREL BISULFATE",     "terms": ["clopidogrel", "antiplatelet"]},
    "omeprazole":        {"fda": "OMEPRAZOLE",                "terms": ["omeprazole", "proton pump inhibitor"]},
    "simvastatin":       {"fda": "SIMVASTATIN",               "terms": ["simvastatin", "statin", "hmg-coa reductase inhibitor"]},
    "atorvastatin":      {"fda": "ATORVASTATIN CALCIUM",      "terms": ["atorvastatin", "statin", "hmg-coa reductase inhibitor"]},
    "clarithromycin":    {"fda": "CLARITHROMYCIN",            "terms": ["clarithromycin", "macrolide", "strong cyp3a4 inhibitor"]},
    "amlodipine":        {"fda": "AMLODIPINE BESYLATE",       "terms": ["amlodipine", "calcium channel blocker"]},
    "metformin":         {"fda": "METFORMIN HYDROCHLORIDE",   "terms": ["metformin"]},
    "glimepiride":       {"fda": "GLIMEPIRIDE",               "terms": ["glimepiride", "sulfonylurea"]},
    "lisinopril":        {"fda": "LISINOPRIL",                "terms": ["lisinopril", "ace inhibitor", "angiotensin converting enzyme inhibitor"]},
    "telmisartan":       {"fda": "TELMISARTAN",               "terms": ["telmisartan", "angiotensin ii receptor blocker", "angiotensin receptor blocker"]},
    "spironolactone":    {"fda": "SPIRONOLACTONE",            "terms": ["spironolactone", "potassium-sparing diuretic", "potassium sparing diuretic"]},
    "levothyroxine":     {"fda": "LEVOTHYROXINE SODIUM",      "terms": ["levothyroxine", "thyroid hormone"]},
    "calcium carbonate": {"fda": "CALCIUM CARBONATE",         "terms": ["calcium carbonate", "antacid", "calcium supplement", "calcium-containing"]},
    "sertraline":        {"fda": "SERTRALINE HYDROCHLORIDE",  "terms": ["sertraline", "ssri", "selective serotonin reuptake inhibitor", "serotonergic"]},
    "tramadol":          {"fda": "TRAMADOL HYDROCHLORIDE",    "terms": ["tramadol", "serotonergic", "opioid"]},
    "digoxin":           {"fda": "DIGOXIN",                   "terms": ["digoxin", "digitalis"]},
    "amiodarone":        {"fda": "AMIODARONE HYDROCHLORIDE",  "terms": ["amiodarone"]},
    "sildenafil":        {"fda": "SILDENAFIL CITRATE",        "terms": ["sildenafil", "pde5 inhibitor", "phosphodiesterase"]},
    "isosorbide mononitrate": {"fda": "ISOSORBIDE MONONITRATE", "terms": ["isosorbide", "nitrate", "nitric oxide donor"]},
}

# brand or local name -> list of generic keys (combination products map to several)
BRANDS = {
    "paracetamol": ["acetaminophen"], "dolo": ["acetaminophen"], "crocin": ["acetaminophen"], "calpol": ["acetaminophen"],
    "ecosprin": ["aspirin"], "disprin": ["aspirin"],
    "brufen": ["ibuprofen"], "combiflam": ["ibuprofen", "acetaminophen"],
    "coumadin": ["warfarin"], "warf": ["warfarin"],
    "clopilet": ["clopidogrel"], "plavix": ["clopidogrel"],
    "omez": ["omeprazole"],
    "atorva": ["atorvastatin"], "lipitor": ["atorvastatin"],
    "amlong": ["amlodipine"],
    "glycomet": ["metformin"], "amaryl": ["glimepiride"],
    "telma": ["telmisartan"], "aldactone": ["spironolactone"],
    "thyronorm": ["levothyroxine"], "eltroxin": ["levothyroxine"],
    "shelcal": ["calcium carbonate"],
    "lanoxin": ["digoxin"], "cordarone": ["amiodarone"], "viagra": ["sildenafil"],
}

# a few names as people type them in Tamil or Hindi script
SCRIPT = {
    "வார்ஃபரின்": "warfarin", "மெட்ஃபார்மின்": "metformin", "பாராசிட்டமால்": "acetaminophen", "ஆஸ்பிரின்": "aspirin",
    "वारफेरिन": "warfarin", "मेटफॉर्मिन": "metformin", "पैरासिटामोल": "acetaminophen", "एस्पिरिन": "aspirin",
}


def _has(text, word):
    return re.search(r"(?<![\w])" + re.escape(word) + r"(?![\w])", text) is not None


def find_known(text: str) -> list[str]:
    """Generic keys named in the text, by generic name, brand or script spelling. Deterministic."""
    t = (text or "").lower()
    out = []
    for g in KNOWN:
        if _has(t, g):
            out.append(g)
    for b, gs in BRANDS.items():
        if _has(t, b):
            out += gs
    for s, g in SCRIPT.items():
        if s in (text or ""):
            out.append(g)
    return list(dict.fromkeys(out))


def normalize(name: str) -> str:
    """Map any name to its generic key if we know it, else the cleaned name itself."""
    n = re.sub(r"[^a-z0-9 \-]", " ", (name or "").lower())
    n = re.sub(r"\b\d+(mg|mcg)?\b", " ", n)
    n = " ".join(n.split())
    if n in KNOWN:
        return n
    for word in n.split():
        if word in BRANDS:
            return BRANDS[word][0]
        if word in KNOWN:
            return word
    hits = find_known(n)
    return hits[0] if hits else n


def terms_for(key: str) -> list[str]:
    return KNOWN.get(key, {}).get("terms", [key])
