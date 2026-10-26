"""Text normalization for narration (no heavy imports - shared by the GPU worker and tests).

MMS-TTS drops punctuation and some digits, so numbers are spelled out and the line is
split into phrases the narrator pauses between.
"""
from __future__ import annotations

import re

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
       "twelve": "twelfth"}


def number_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if 1900 <= n <= 2099:   # years the way people say them
        hi, lo = divmod(n, 100)
        return number_words(hi) + " " + ("hundred" if lo == 0 else ("oh " + ONES[lo] if lo < 10 else number_words(lo)))
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + number_words(n % 100))
    return " ".join(ONES[int(d)] for d in str(n))


def ordinal_words(words: str) -> str:
    *head, last = words.split()
    if last in ORD:
        last = ORD[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last = last + "th"
    return " ".join(head + [last])


def spell_numbers(text: str) -> str:
    text = re.sub(r"(\d+)(st|nd|rd|th)\b", lambda m: ordinal_words(number_words(int(m.group(1)))), text)
    text = re.sub(r"\d+", lambda m: number_words(int(m.group(0))), text)
    return text.replace("&", " and ").replace("%", " percent")


def phrases(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[,.;:!?—–]+|\s-\s", spell_numbers(text))]
    return [p for p in parts if re.search(r"[A-Za-z֐-׿]", p)]
