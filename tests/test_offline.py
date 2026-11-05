"""Offline tests: no AWS, no network. Run: python -m pytest -q tests"""
from agent import lexicon, openfda, safety, tools


def _fake(key, sections):
    openfda._mem[key] = {"key": key, "found": True, "effective_time": "20260101", "sections": sections}


def test_brands_map_to_generics():
    assert lexicon.find_known("I take Ecosprin and Dolo 650") == ["acetaminophen", "aspirin"] or \
        set(lexicon.find_known("I take Ecosprin and Dolo 650")) == {"aspirin", "acetaminophen"}
    assert set(lexicon.find_known("Combiflam")) == {"ibuprofen", "acetaminophen"}
    assert lexicon.normalize("Glycomet 500") == "metformin"


def test_red_flags_in_three_languages():
    assert safety.red_flag("Should I take a double dose today?")[0] == "dose"
    assert safety.red_flag("இன்று இரண்டு மடங்கு எடுக்கலாமா?")[0] == "dose"
    assert safety.red_flag("क्या मैं खुराक दोगुनी कर सकता हूँ?")[0] == "dose"
    assert safety.red_flag("chest pain after the tablet")[0] == "emergency"
    assert safety.red_flag("எனக்கு வாழ விருப்பமில்லை")[0] == "mental"
    assert safety.red_flag("I take warfarin. Can I take Ecosprin?")[0] is None


def test_dosing_advice_and_safe_claims():
    assert safety.dosing_advice("Take 2 tablets after food.")
    assert safety.dosing_advice("You can take 500 mg at night.")
    assert not safety.dosing_advice("Do not stop or change any dose on your own.")
    assert safety.safety_claims("These two are safe to take together.")
    assert not safety.safety_claims("The labels do not name each other.")
    assert not safety.safety_claims("That does not prove they are safe together.")
    assert safety.safety_claims("They do not interact. You can take them.")


def test_interaction_found_by_class_and_quoted():
    _fake("warfarin", {"drug_interactions": "Drugs that increase bleeding risk include NSAIDs and antiplatelet agents."})
    _fake("ibuprofen", {"warnings": "Ask a doctor if you take a blood thinning (anticoagulant) drug."})
    flags = openfda.interactions(["warfarin", "ibuprofen"])
    assert flags and set(flags[0]["drugs"]) == {"warfarin", "ibuprofen"}
    cites = {q["cite"] for q in flags[0]["quotes"]}
    assert cites == {"warfarin:drug_interactions", "ibuprofen:warnings"}
    assert "warfarin:drug_interactions" in tools.guidance_ids()


def test_silent_labels_give_no_flag():
    _fake("metformin", {"drug_interactions": "Carbonic anhydrase inhibitors may cause metabolic acidosis."})
    _fake("atorvastatin", {"drug_interactions": "Strong CYP3A4 inhibitors increase atorvastatin levels."})
    assert openfda.interactions(["metformin", "atorvastatin"]) == []


def test_language_detection():
    assert tools.language_of("நான் warfarin") == "ta"
    assert tools.language_of("मैं warfarin") == "hi"
    assert tools.language_of("I take warfarin") == "en"


def test_checker_verdict_parsing():
    from agent.app import verdict
    assert verdict("PASS") == (True, [])
    ok, probs = verdict("REVISE\n- says it is safe")
    assert not ok and probs == ["says it is safe"]
    assert verdict("Looks fine")[0] is False  # anything unclear is a problem


def test_fixed_answer_has_no_model_words_and_no_dose():
    from agent.app import fixed_answer
    flags = [{"drugs": ["warfarin", "ibuprofen"], "quotes": [{"label_of": "warfarin", "section": "drug_interactions",
                                                             "matched": "ibuprofen", "cite": "warfarin:drug_interactions"}]}]
    a = fixed_answer(["warfarin", "ibuprofen"], flags)
    assert "warfarin label names ibuprofen" in a and not safety.dosing_advice(a) and not safety.safety_claims(a)
