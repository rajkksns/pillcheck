"""Safety rules in code. A phrase list misses wording it has not seen: add every miss `ss measure` finds.

The red-flag check runs on the user's own words AND on Amazon Translate's English version of them, so a Tamil or
Hindi message is caught by both lists.
"""
import re

EMERGENCY = [  # possible poisoning, overdose or a reaction: call 108 now
    "overdose", "took too many", "took too much", "swallowed too many", "by mistake", "accidentally", "chest pain",
    "can't breathe", "cannot breathe", "trouble breathing", "short of breath", "fainted", "unconscious",
    "passed out", "seizure", "vomiting blood", "black stool", "blood in stool", "bleeding won't stop",
    "swollen face", "face swelling", "throat swelling",
    "நெஞ்சு வலி", "மூச்சு விட முடியவில்லை", "மயக்கம்", "தவறுதலாக", "கருப்பு மலம்",
    "सीने में दर्द", "सांस नहीं", "बेहोश", "गलती से", "मल काला", "काला मल", "खून की उल्टी",
]
MENTAL = [  # thoughts of self-harm: Tele-MANAS 14416, and 108 if in danger
    "suicide", "kill myself", "end my life", "want to die", "don't want to live", "do not want to live",
    "all the tablets at once", "all my tablets at once",
    "தற்கொலை", "வாழ விருப்பமில்லை", "எல்லா மாத்திரைகளையும் ஒரேயடியாக",
    "आत्महत्या", "जीना नहीं चाहता", "जीना नहीं चाहती", "मरना चाहता", "मरना चाहती",
]
DOSE = [  # dose changes: a pharmacist or doctor decides, never this assistant
    "double dose", "double the dose", "double my", "extra dose", "extra tablet", "skip my", "skip the",
    "stop taking", "can i stop", "should i stop", "increase the dose", "increase my dose", "reduce the dose",
    "reduce my dose", "change my dose", "change the dose", "how many tablets", "how much should i take",
    "how many mg", "take two tablets", "take more", "double",
    "இரண்டு மடங்கு", "இரட்டிப்பு", "அதிக மாத்திரை", "நிறுத்தலாமா", "நிறுத்தட்டுமா", "டோஸ்", "அளவை மாற்ற", "அளவை கூட்ட",
    "दोगुनी", "दोगुना", "डबल", "ज़्यादा गोलियां", "ज्यादा गोलियां", "बंद कर दूं", "बंद कर सकता", "बंद कर सकती", "खुराक",
]

HANDOFF = {
    "emergency": {
        "en": "This could be an emergency. Call 108 now or go to the nearest hospital. Take the medicine strips or boxes with you.",
        "ta": "இது அவசரநிலையாக இருக்கலாம். உடனே 108 ஐ அழைக்கவும் அல்லது அருகிலுள்ள மருத்துவமனைக்குச் செல்லவும். மருந்து அட்டைகள் அல்லது பெட்டிகளை உடன் எடுத்துச் செல்லவும்.",
        "hi": "यह आपात स्थिति हो सकती है। तुरंत 108 पर कॉल करें या नज़दीकी अस्पताल जाएं। दवा के पत्ते या डिब्बे साथ ले जाएं।"},
    "mental": {
        "en": "You are not alone. Please call Tele-MANAS on 14416 now, free and any time. If you are in danger, call 108.",
        "ta": "நீங்கள் தனியாக இல்லை. இப்போதே Tele-MANAS 14416 ஐ அழைக்கவும், இது இலவசம், எந்த நேரத்திலும். ஆபத்து இருந்தால் 108 ஐ அழைக்கவும்.",
        "hi": "आप अकेले नहीं हैं। अभी Tele-MANAS 14416 पर कॉल करें, यह मुफ़्त है और हर समय उपलब्ध है। खतरा हो तो 108 पर कॉल करें।"},
    "dose": {
        "en": "This assistant does not answer questions about changing, doubling, skipping or stopping a dose. Please ask your pharmacist or doctor today.",
        "ta": "மருந்தின் அளவை மாற்றுவது, இரட்டிப்பாக்குவது, தவிர்ப்பது அல்லது நிறுத்துவது பற்றி இந்த உதவியாளர் பதில் அளிக்காது. இன்றே உங்கள் மருந்தாளர் அல்லது மருத்துவரிடம் கேளுங்கள்.",
        "hi": "यह सहायक दवा की खुराक बदलने, दोगुनी करने, छोड़ने या बंद करने के सवालों का जवाब नहीं देता। कृपया आज ही अपने फार्मासिस्ट या डॉक्टर से पूछें।"},
}
NOT_FOUND = {
    "en": "I could not find an official label for: {names}. I will not guess about a medicine I cannot check. Please show the strip or box to your pharmacist.",
    "ta": "{names} க்கான அதிகாரப்பூர்வ மருந்து லேபிளை என்னால் கண்டுபிடிக்க முடியவில்லை. சரிபார்க்க முடியாத மருந்தைப் பற்றி நான் ஊகிக்க மாட்டேன். மாத்திரை அட்டை அல்லது பெட்டியை உங்கள் மருந்தாளரிடம் காட்டுங்கள்.",
    "hi": "मुझे {names} का आधिकारिक दवा लेबल नहीं मिला। जिस दवा की जांच नहीं कर सकता, उसके बारे में मैं अनुमान नहीं लगाऊंगा। कृपया दवा का पत्ता या डिब्बा अपने फार्मासिस्ट को दिखाएं।",
}
NO_MEDICINE = {
    "en": "Please tell me the names of your medicines, as printed on the strip or box, and I will check their official labels.",
    "ta": "உங்கள் மருந்துகளின் பெயர்களை, அட்டை அல்லது பெட்டியில் உள்ளபடி, சொல்லுங்கள். அவற்றின் அதிகாரப்பூர்வ லேபிள்களை நான் சரிபார்க்கிறேன்.",
    "hi": "कृपया अपनी दवाओं के नाम बताएं, जैसे पत्ते या डिब्बे पर लिखे हैं, और मैं उनके आधिकारिक लेबल देखूंगा।",
}
PHARMACIST = {
    "en": "Show this to your pharmacist or doctor before you change anything.",
    "ta": "எதையும் மாற்றும் முன் இதை உங்கள் மருந்தாளர் அல்லது மருத்துவரிடம் காட்டுங்கள்.",
    "hi": "कुछ भी बदलने से पहले इसे अपने फार्मासिस्ट या डॉक्टर को दिखाएं।",
}


STEPS_EN = ["Show this answer and your medicine strips or boxes to your pharmacist or doctor.",
            "Do not start, stop or change any medicine on your own."]


def red_flag(*texts: str) -> tuple[str | None, list[str]]:
    """('emergency' | 'mental' | 'dose' | None, matched phrases). Most serious kind wins."""
    t = " ".join(x for x in texts if x).lower()
    for kind, words in (("mental", MENTAL), ("emergency", EMERGENCY), ("dose", DOSE)):
        hits = [w for w in words if w.lower() in t]
        if hits:
            return kind, hits
    return None, []


_VERB = r"(take|taking|use|increase|decrease|reduce|lower|raise|double|skip|stop|halve|split|cut)"
_AMOUNT = r"(\d+(\.\d+)?\s?(mg|mcg|g|ml|tablets?|pills?|capsules?)|dose|doses|dosage)"
DOSE_ADVICE = re.compile(_VERB + r"\b[^.\n]{0,40}\b" + _AMOUNT, re.I)
NUMBER_DOSE = re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg)\b", re.I)
NEGATED = re.compile(r"\b(do not|don't|never|not|without|before|ask|check with|talk to)\b", re.I)
SAFE_CLAIM = re.compile(r"\b(safe to take|safe together|no interaction|won't interact|will not interact|"
                        r"do not interact|don't interact|no problem taking|nothing to worry)\b", re.I)


def dosing_advice(text: str) -> list[str]:
    """Sentences that tell the person what dose to take. Label quotes are checked separately, never here."""
    bad = []
    for s in re.split(r"(?<=[.!?])\s+|\n", text or ""):
        if NUMBER_DOSE.search(s) or (DOSE_ADVICE.search(s) and not NEGATED.search(s)):
            bad.append(s.strip())
    return bad


HEDGE = re.compile(r"\b(not prove|doesn't prove|does not prove|do not prove|don't prove|does not mean|doesn't mean|"
                   r"do not mean|no proof|not necessarily|cannot say|can't say|not known|unknown|not confirm)\b", re.I)


def safety_claims(text: str) -> list[str]:
    """'Safe together' claims, sentence by sentence. A label that is silent is not a label that says safe.
    A sentence that says the labels do NOT prove safety is the warning we want, not a claim."""
    bad = []
    for s in re.split(r"(?<=[.!?])\s+|\n", text or ""):
        m = SAFE_CLAIM.search(s)
        if m and not HEDGE.search(s):
            bad.append(m.group(0))
    return bad
