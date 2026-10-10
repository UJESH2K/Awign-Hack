"""Annotation lint: mistakes visible in the annotation file itself, found before a frame is decoded.

    format       end before start, zero length, times outside the video, empty labels, duplicate ids
    duplicates   the same action labelled twice over the same seconds
    consistency  the verb/noun fields disagree with the narration; a verb or noun that is a likely
                 typo of one the rest of the batch uses (suggests the spelling the batch uses)
    length       segments far longer than any real single action

Each finding is an Issue like the video checks, so the tester sees one list.
"""
from collections import Counter
from difflib import get_close_matches

from .checks import Issue
from .clip_io import Segment

LONG_S = 45.0


def vocabulary(all_segments: list[Segment]) -> tuple[Counter, Counter]:
    verbs, nouns = Counter(), Counter()
    for s in all_segments:
        if s.verb:
            verbs[s.verb.lower().strip()] += 1
        for w in (s.noun or "").lower().split():
            nouns[w] += 1
    return verbs, nouns


def _typo(word: str, vocab: Counter, min_count: int = 3) -> str | None:
    """A rare word one or two letters away from a common word in the batch."""
    w = word.lower().strip()
    if not w or vocab.get(w, 0) >= 2:
        return None
    common = [k for k, c in vocab.items() if c >= min_count and k != w]
    m = get_close_matches(w, common, n=1, cutoff=0.8)
    return m[0] if m else None


def run(segments: list[Segment], duration: float, verbs: Counter | None = None, nouns: Counter | None = None,
        start: int = 500) -> list[Issue]:
    verbs = verbs or vocabulary(segments)[0]
    nouns = nouns or vocabulary(segments)[1]
    out: list[Issue] = []

    def add(**k):
        out.append(Issue(id=f"i{start + len(out)}", group="annotation", **k))

    seen_ids = Counter(s.id for s in segments)
    for s in segments:
        t = max(0.0, min(s.start, duration))
        if s.end <= s.start:
            add(segment=s.id, kind="inverted times", severity="fix", t=t, title=f"Ends before it starts ({s.start:.2f} → {s.end:.2f} s)",
                detail="Start and end are swapped or mistyped.", nudge=f"Swap start and end of '{s.narration}'.",
                suggestion={"field": "swap", "value": [s.end, s.start]})
        if s.start < 0 or s.end > duration + 0.5:
            add(segment=s.id, kind="out of range", severity="fix", t=t,
                title=f"Outside the video ({s.start:.1f}–{s.end:.1f} s, video is {duration:.1f} s)",
                detail="Times point past the end of the footage: wrong video, or a typo in the timestamp.",
                nudge="Check which video this segment belongs to.")
        if not s.narration.strip():
            add(segment=s.id, kind="empty label", severity="fix", t=t, title="No label", detail="The segment has times but no action.",
                nudge="Name the action or drop the segment.")
        if seen_ids[s.id] > 1:
            add(segment=s.id, kind="duplicate id", severity="fix", t=t, title=f"Id '{s.id}' is used {seen_ids[s.id]} times",
                detail="Two segments share an id; the client's loader will keep only one.", nudge="Give the segment a unique id.")
        if s.end - s.start > LONG_S:
            add(segment=s.id, kind="too long", severity="check", t=t, t_end=s.end, title=f"Lasts {s.end - s.start:.0f} s",
                detail="Longer than any single hand action; usually several actions under one label.", nudge="Split into individual actions.")
        words = s.narration.lower().split()
        # A segment the product itself drafted carries placeholders ("?", "unlabelled action
        # (to name)"). Flagging those as the annotator's mistake is noise; the empty-label
        # nudge below already asks for a name.
        placeholder = s.verb.strip() in {"?", "-"} or "unlabelled action" in s.narration.lower()
        if placeholder:
            add(segment=s.id, kind="empty label", severity="fix", t=t, title="Still needs a name",
                detail="This segment was drafted automatically and has no action name yet.",
                nudge="Name the action, or drop the segment.")
        if not placeholder and s.verb and words and s.verb.lower().split("-")[0] not in s.narration.lower():
            add(segment=s.id, kind="fields disagree", severity="check", t=t,
                title=f"Verb field '{s.verb}' does not match the label '{s.narration}'",
                detail="The structured fields and the free-text label say different things.", nudge="Make the verb field match the label.")
        tv = _typo(s.verb or (words[0] if words else ""), verbs)
        if tv:
            add(segment=s.id, kind="typo", severity="fix", t=t, title=f"'{s.verb}' looks like a typo of '{tv}'",
                detail=f"The rest of the batch uses '{tv}' ({verbs[tv]} times).", nudge=f"Use '{tv}', the batch's spelling.",
                suggestion={"field": "narration", "value": s.narration.replace(s.verb, tv, 1) if s.verb in s.narration else s.narration})
        for w in (s.noun or "").lower().split():
            tn = _typo(w, nouns)
            if tn:
                add(segment=s.id, kind="typo", severity="fix", t=t, title=f"'{w}' looks like a typo of '{tn}'",
                    detail=f"The rest of the batch uses '{tn}' ({nouns[tn]} times).", nudge=f"Use '{tn}', the batch's spelling.",
                    suggestion={"field": "narration", "value": s.narration.replace(w, tn, 1)})
                break
    # the same action labelled twice over the same seconds
    by_label: dict[str, list[Segment]] = {}
    for s in segments:
        by_label.setdefault(s.narration.lower().strip(), []).append(s)
    for label, segs in by_label.items():
        segs = sorted(segs, key=lambda x: x.start)
        for a, b in zip(segs, segs[1:]):
            inter = min(a.end, b.end) - max(a.start, b.start)
            if inter > 0.6 * min(a.end - a.start, b.end - b.start) > 0:
                add(segment=b.id, kind="duplicate", severity="fix", t=b.start, t_end=min(a.end, b.end),
                    title=f"'{b.narration}' is labelled twice over the same seconds",
                    detail=f"Overlaps an identical segment ({a.start:.1f}–{a.end:.1f} s) by {inter:.1f} s.", nudge="Drop the duplicate.")
    return out
