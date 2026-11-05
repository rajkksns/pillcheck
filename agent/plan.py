"""Structured outputs. Code owns medicines, not_found and interactions; the model owns only the explanation."""
from typing import Literal

from pydantic import BaseModel, Field


class Medicines(BaseModel):
    names: list[str] = Field(default_factory=list, description="Every medicine name the user mentions, exactly as written")


class Explanation(BaseModel):
    answer_en: str = Field(default="", description="Plain English, short sentences, at most 120 words")
    steps: list[str] = Field(default_factory=list, description="2-3 short things to do next, in English")
    citations: list[str] = Field(default_factory=list, description="Ids from the FACTS block, like warfarin:drug_interactions")


class Critique(BaseModel):
    ok: bool = False
    problems: list[str] = Field(default_factory=list)


class Flag(BaseModel):
    drugs: list[str]
    label_says: str = Field(description="What the label says, quoted")
    citation: str


class Answer(BaseModel):
    language: Literal["en", "ta", "hi"] = "en"
    medicines: list[str] = Field(default_factory=list, description="Medicines found on an official label")
    not_found: list[str] = Field(default_factory=list, description="Medicines with no official label found")
    interactions: list[Flag] = Field(default_factory=list)
    answer_en: str = Field(default="", description="The answer in English")
    answer: str = Field(default="", description="The answer in the user's language")
    steps: list[str] = Field(default_factory=list, description="Next steps, in the user's language")
    escalation: str = Field(default="", description="Who to ask, in the user's language")
    citations: list[str] = Field(default_factory=list)
