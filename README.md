# PillCheck

**What the official labels say about the medicines you take together, in English, Tamil or Hindi.**

An adult on four or five medicines from different doctors often has nobody who looks at the whole list. The leaflet
is long, in small English print, and the warning that matters ("taking this with aspirin increases bleeding") is on
page three. PillCheck takes the medicines a person names, by generic or Indian brand name, finds each one's official
US FDA label, and tells them in plain words which of their medicines the labels warn about together. It quotes the
label for every warning. It never gives a dose, never says a combination is safe, and hands dose questions,
emergencies and self-harm to a person.

Built with the [Strands Agents SDK](https://strandsagents.com) on Amazon Bedrock (Amazon Nova 2 Lite) and Amazon Translate.

> PillCheck is an explainer, not medical advice. Labels are US FDA labels; Indian products can differ. Always ask a pharmacist or doctor.

## The rule: code decides, the model explains

| Step | Decided by | Strands piece |
|---|---|---|
| Red flags (overdose, chest pain, black stool, self-harm, any dose change) in English, Tamil, Hindi | Code (`agent/safety.py`) | Two hooks: `BeforeModelCallEvent` cancels the reader, `BeforeNodeCallEvent` cancels the graph. A fixed reply sends the person to 108, Tele-MANAS 14416, or their pharmacist |
| Tamil or Hindi in, English out, and back | Amazon Translate | code around the agents; red flags are checked on both the original words and the translation |
| Which medicines were named | Model lists names, code maps brands (Ecosprin, Dolo, Glycomet, Telma...) to generics | `Agent` with structured output |
| Does each medicine have an official label | Code, openFDA | cached in `agent/data/labels/` with set id and effective date |
| Which pairs the labels link | Code: label A names B, or B's drug class (NSAID, statin, potassium-sparing diuretic...) | quoted, cited as `warfarin:drug_interactions` |
| Plain-English explanation of those facts | Model | `GraphBuilder`: explainer -> checker, at most 2 tries |
| The explainer may only read labels of this person's medicines | Code | `InterventionHandler` denies any other label read |
| Final checks: every flagged pair explained, no dose advice, no "safe together", valid citations | Code | fail closed: if any check fails, a fixed answer written by code from the label quotes ships instead |

A medicine with no official label (an Ayurvedic churna, a misspelt or unknown brand) gets "I could not find an
official label for it. I will not guess." and a pointer to the pharmacist.

## Run it

```
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
aws login            # an AWS account with Bedrock (Amazon Nova 2 Lite) and Amazon Translate in us-east-1
python -m agent.app "I take warfarin for my heart. Can I also take Ecosprin?"
python -m agent.app "நான் warfarin எடுத்துக்கொள்கிறேன். தலைவலிக்கு Combiflam சாப்பிடலாமா?" --json
python -m agent.check_cases      # cases vs real labels, no Bedrock calls
python -m pytest -q tests        # offline tests, no AWS
```

## Measured

`results/MEASURE.md` compares PillCheck with a one-prompt baseline: the same model, the same FDA label text pasted
into the prompt, no hooks, no code facts, no checker. 33 human-reviewed cases: 12 English, 11 Tamil, 10 Hindi;
10 red-flag cases, 4 medicines with no label, 19 label questions across 6 groups of people.

## Limits

- Labels are US FDA labels in English. Generic names match Indian medicines; strengths and fillers can differ.
- The brand list in `agent/lexicon.py` is short and needs a pharmacist's review.
- The phrase lists for red flags miss wording they have not seen. Every miss found goes into the list and the cases.
- A label that does not name another medicine does not prove the two are safe together. PillCheck says so.
- Tamil and Hindi fixed replies were written by the author and should be checked by native speakers.

## License

MIT. Drug label text: openFDA, U.S. Food and Drug Administration (public domain). `ship_kit/` from
[strands-ship](https://github.com/logesh4v/strands-ship) (Apache-2.0).
