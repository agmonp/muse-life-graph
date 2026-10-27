"""Film templates: the story shape of each kind of film, given to the screenwriter.

A template is not a fixed timeline. It names the beats of the arc, how much of the
film each one gets, and the rules that make that kind of film feel right (a
wedding needs both partners, a friends film runs faster and lighter). The producer
picks the template from the request; the owner can also pick it in the Edit Room.
`check()` reports beats the script left out, so the gap shows in the crew log.
"""
from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "birthday": {
        "label": "Birthday",
        "seconds": 70, "music_mood": "warm", "sec_per_photo": 4.0,
        "beats": [
            ("hello", 0.12, "the honoree today, face clearly visible - the title sits on it"),
            ("roots", 0.25, "where it began: the oldest pictures, in date order"),
            ("people", 0.28, "the people around them - kids, grandkids, friends - one relationship per scene"),
            ("peak", 0.22, "the birthday itself or the strongest blessing/toast, voice lines here"),
            ("together", 0.13, "everyone together, a warm complete ending"),
        ],
        "rules": ["Count the years only if the brief gives the age.",
                  "Narration may say the age once, in the hello or the peak, never both."],
    },
    "wedding": {
        "label": "Wedding / anniversary",
        "seconds": 80, "music_mood": "tender", "sec_per_photo": 4.5,
        "beats": [
            ("two_lives", 0.22, "each partner before they met - one scene each, alternating if there is material"),
            ("meeting", 0.18, "the first pictures of the two of them together"),
            ("the_day", 0.25, "the wedding day itself: the vows, the first dance, the toasts"),
            ("blessings", 0.20, "family and friends' wishes - recorded blessings go here"),
            ("ahead", 0.15, "the two of them now, ending on both faces"),
        ],
        "rules": ["Both partners must be on screen in the first and the last scene.",
                  "Never show an ex-partner as part of the couple's story."],
    },
    "friends": {
        "label": "Friends",
        "seconds": 50, "music_mood": "playful", "sec_per_photo": 3.0,
        "beats": [
            ("the_gang", 0.15, "the group as it is today"),
            ("adventures", 0.40, "trips, parties, silly faces - fast cuts, most energy"),
            ("inside_jokes", 0.20, "moments that are funny to this group (laughing faces, odd objects)"),
            ("tribute", 0.25, "one warm line or blessing, then the group together again"),
        ],
        "rules": ["Keep narration to 2 lines at most - let the pictures be funny.",
                  "Prefer pictures where several friends are visible."],
    },
    "family": {
        "label": "Family",
        "seconds": 75, "music_mood": "warm", "sec_per_photo": 4.0,
        "beats": [
            ("home", 0.12, "the family today"),
            ("generations", 0.30, "the oldest generation first, then their children, then the grandchildren"),
            ("everyday", 0.28, "ordinary days: cooking, trips, holidays"),
            ("milestones", 0.18, "the big days - weddings, births, birthdays - voice lines here"),
            ("all_of_us", 0.12, "as many of the family as possible in one picture"),
        ],
        "rules": ["Give every family member at least one scene where they are the focus, if the material allows.",
                  "Order generations by date of the pictures, not by guess."],
    },
}

OCCASION_TO_TEMPLATE = {"birthday": "birthday", "wedding": "wedding", "anniversary": "wedding",
                        "friends": "friends", "family": "family", "memorial": "family", "other": "family"}


def pick(occasion: str, chosen: str | None = None) -> str:
    if chosen in TEMPLATES:
        return chosen
    return OCCASION_TO_TEMPLATE.get((occasion or "").lower(), "family")


def for_prompt(name: str, target_seconds: int) -> str:
    t = TEMPLATES[name]
    beats = "\n".join(f"  - {b} (~{round(share * target_seconds)} s): {what}" for b, share, what in t["beats"])
    rules = "\n".join(f"  - {r}" for r in t["rules"])
    return (f"TEMPLATE: {t['label']} film. Give every scene a `beat` from this list, in this order "
            f"(a beat may have several scenes; skip a beat only if no moment fits it):\n{beats}\n"
            f"About {t['sec_per_photo']} s per photo.\nTEMPLATE RULES:\n{rules}")


def check(name: str, script: dict) -> list[str]:
    """Beats the script skipped or put out of order (for the crew log; the film is still made)."""
    order = [b for b, _, _ in TEMPLATES[name]["beats"]]
    used = [sc.get("beat") for sc in sorted(script["scenes"], key=lambda s: s["order"])]
    notes = [f"no scene for the '{b}' beat" for b in order if b not in used]
    ranks = [order.index(b) for b in used if b in order]
    if ranks != sorted(ranks):
        notes.append("beats out of the template's order")
    return notes


def catalog() -> list[dict]:
    return [{"id": k, "label": v["label"], "seconds": v["seconds"], "beats": [b for b, _, _ in v["beats"]]}
            for k, v in TEMPLATES.items()]
