"""Amazon Translate in and out. If Translate fails, the agent keeps working in English and says so in meta."""
import os
from functools import lru_cache

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")


@lru_cache(maxsize=1)
def _client():
    return boto3.client("translate", region_name=REGION)


def translate(text: str, src: str, dst: str) -> tuple[str, bool]:
    """(translated text, ok). Same language or empty text is returned as is."""
    if not text or src == dst:
        return text, True
    try:
        r = _client().translate_text(Text=text[:9000], SourceLanguageCode=src, TargetLanguageCode=dst)
        return r["TranslatedText"], True
    except Exception:
        return text, False
