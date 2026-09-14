"""Offline replay scoring. Timing windows describe proximity, not ground truth.

Annotations may provide ``true_codes`` (or legacy ``true_code``), explicitly
``invalid_codes`` and ``negative_windows`` (verified ordinary speech).
Unlisted codes stay unjudged unless ``code_labels_complete`` is explicitly true.
"""
from __future__ import annotations

from collections import Counter
import math
import statistics

PROMPT_LEVELS = ("high", "medium", "semantic")


def _speech_latencies(references: list[dict], events: dict, duration: float) -> list[dict]:
    """Match each spoken cue/code once, independently of platform timestamps.

    ``end`` is the annotated end of the spoken cue or complete code. An explicit
    ``match_until`` keeps unrelated later alerts from hiding a missed cue.
    Negative latency is retained: segment-level timing can include trailing
    speech, and a detector may legitimately fire before that segment ends.
    """
    outputs = sorted(
        [dict(a, kind="prompt") for a in events["alerts"] if a["level"] in PROMPT_LEVELS]
        + [dict(c, kind="code") for c in events["codes"]], key=lambda event: event["t"])
    used = set()
    rows = []
    for reference in sorted(references, key=lambda item: item["start"]):
        kind = reference["kind"]
        start, end, until = (reference[key] for key in ("start", "end", "match_until"))
        if kind not in ("prompt", "code") or not all(
                math.isfinite(t) for t in (start, end, until)) or not 0 <= start <= end <= until <= duration:
            raise ValueError("Invalid speech timing annotation")
        if kind == "code":
            code = reference.get("code", "")
            if not isinstance(code, str) or len(code) != 4 or not code.isascii() or not code.isdigit():
                raise ValueError("Speech timing requires a four-digit code")
        match = next((i for i, event in enumerate(outputs)
                      if i not in used and event["kind"] == kind
                      and start <= event["t"] <= until
                      and (kind == "prompt" or event["code"] == reference["code"])), None)
        detected = outputs[match]["t"] if match is not None else None
        if match is not None:
            used.add(match)
        rows.append({**reference, "detected_at": detected,
                     "latency_seconds": round(detected - end, 3) if detected is not None else None})
    return rows


def _summarize_latencies(rows: list[dict], kind: str) -> dict:
    references = [event for row in rows for event in row["speech_latencies"] if event["kind"] == kind]
    values = [event["latency_seconds"] for event in references if event["detected_at"] is not None]
    return {
        "annotated_events": len(references), "detected_events": len(values),
        "missed_events": len(references) - len(values),
        "median_seconds": round(statistics.median(values), 3) if values else None,
        "min_seconds": min(values) if values else None,
        "max_seconds": max(values) if values else None,
    }


def _intervals(windows, duration):
    """Clip and merge annotated intervals so overlap cannot inflate coverage."""
    merged = []
    for start, end in sorted(windows):
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError("Invalid annotation interval")
        start, end = max(0.0, start), min(duration, end)
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def score_clip(meta: dict, events: dict, before: float = 240, after: float = 120,
               *, annotation: dict | None = None) -> dict:
    anchor = float(meta.get("rollcall_offset", 0.0))
    duration = float(events["audio_seconds"])
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("Invalid audio duration")
    window = meta.get("window") or [anchor - before, anchor + after]
    proximity = _intervals([window], duration)
    inside = lambda event: window[0] <= event["t"] <= window[1]
    prompts = sorted((a for a in events["alerts"] if a["level"] in PROMPT_LEVELS),
                     key=lambda a: a["t"])
    all_codes = sorted(events["codes"], key=lambda c: c["t"])
    in_window = [a for a in prompts if inside(a)]
    codes = [c for c in all_codes if inside(c)]
    label = annotation or {}
    announced = label.get("announced")
    expected = label.get("true_code", meta.get("expected_code"))
    expected_codes = label.get("true_codes", [expected] if expected is not None else [])
    invalid_codes = label.get("invalid_codes", [])
    for values in (expected_codes, invalid_codes):
        if not isinstance(values, list) or any(
                not isinstance(code, str) or len(code) != 4 or not code.isascii() or not code.isdigit()
                for code in values):
            raise ValueError("Code annotations must contain four-digit strings")
    expected_codes = list(dict.fromkeys(expected_codes))
    if set(expected_codes) & set(invalid_codes):
        raise ValueError("A code cannot be both valid and invalid in the same annotation")
    expected = expected_codes[0] if len(expected_codes) == 1 else None
    negative = _intervals(
        [[0, duration]] if announced == "nothing_audible" else label.get("negative_windows", []),
        duration)
    is_negative = lambda event: any(lo <= event["t"] < hi or event["t"] == hi == duration
                                    for lo, hi in negative)
    false_prompts = sum(is_negative(a) for a in prompts)
    def classify(event):
        if is_negative(event) or event["code"] in invalid_codes:
            return False
        if event["code"] in expected_codes:
            return True
        if label.get("code_labels_complete", False):
            return False
        # A lesson can have multiple sign-ins. One known code is not evidence
        # that every other number emitted in the clip is a recognition error.
        return None

    judgments = [classify(c) for c in all_codes]
    wrong = [c["code"] for c, judgment in zip(all_codes, judgments) if judgment is False]
    unjudged = [c["code"] for c, judgment in zip(all_codes, judgments) if judgment is None]
    recalled_codes = [code for code in expected_codes
                      if any(c["code"] == code and classify(c) is True for c in all_codes)]
    recalled = len(recalled_codes) == len(expected_codes) if expected_codes else None
    correct = (False if not recalled or wrong else None if unjudged else True) if expected_codes else None
    return {
        "clip_id": meta.get("clip_id"), "course": meta.get("course"),
        "by_self": meta.get("by_self"), "rollcall_offset": anchor,
        "announced": announced, "annotation_present": annotation is not None,
        "prompt_detected": bool(in_window),
        "prompt_delay": round(in_window[0]["t"] - anchor, 2) if in_window else None,
        "prompt_reason": in_window[0]["reason"] if in_window else None,
        "prompt_text": in_window[0]["text"] if in_window else None,
        "codes": [c["code"] for c in codes],
        "code_delay": round(codes[0]["t"] - anchor, 2) if codes else None,
        "speech_latencies": _speech_latencies(label.get("speech_events", []), events, duration),
        "expected_code": expected, "expected_codes": expected_codes,
        "recalled_codes": recalled_codes, "code_recalled": recalled,
        "code_correct": correct,
        "first_code_correct": judgments[0] if judgments else None,
        "last_code_correct": judgments[-1] if judgments else None,
        "wrong_codes": wrong, "unjudged_codes": unjudged,
        "judged_code_events": len(all_codes) - len(unjudged),
        "correct_code_events": sum(judgment is True for judgment in judgments),
        "prompts_outside_window": sum(not inside(a) for a in prompts),
        "codes_outside_window": sum(not inside(c) for c in all_codes),
        "outside_window_seconds": round(duration - sum(hi - lo for lo, hi in proximity), 3),
        "false_prompts_in_annotated_negatives": false_prompts,
        "annotated_negative_seconds": round(sum(hi - lo for lo, hi in negative), 3),
        "finals": len(events["finals"]), "audio_seconds": duration,
    }


def summarize_scores(rows: list[dict]) -> dict:
    judged = [r for r in rows if r["expected_codes"]]
    negative_seconds = sum(r["annotated_negative_seconds"] for r in rows)
    false_prompts = sum(r["false_prompts_in_annotated_negatives"] for r in rows)
    code_events = sum(r["judged_code_events"] for r in rows)
    correct_events = sum(r["correct_code_events"] for r in rows)
    unjudged_events = sum(len(r["unjudged_codes"]) for r in rows)
    return {
        "clips": len(rows),
        "annotated_clips": sum(r["annotation_present"] for r in rows),
        "unannotated_clips": [r["clip_id"] for r in rows if not r["annotation_present"]],
        "categories": dict(Counter(r["announced"] or "unannotated" for r in rows)),
        "code_labeled_clips": len(judged),
        "reference_codes": sum(len(r["expected_codes"]) for r in judged),
        "recalled_reference_codes": sum(len(r["recalled_codes"]) for r in judged),
        "code_recalled_clips": sum(r["code_recalled"] for r in judged),
        "code_correct_without_wrong_output_clips": sum(r["code_correct"] is True for r in judged),
        "code_verification_pending_clips": sum(r["code_correct"] is None for r in judged),
        "wrong_code_events": code_events - correct_events,
        "judged_code_events": code_events,
        "unjudged_code_events": unjudged_events,
        "code_judgment_coverage": code_events / (code_events + unjudged_events)
        if code_events + unjudged_events else None,
        "code_precision": correct_events / code_events if code_events else None,
        "prompt_latency": _summarize_latencies(rows, "prompt"),
        "code_latency": _summarize_latencies(rows, "code"),
        "false_prompts_in_annotated_negatives": false_prompts,
        "annotated_negative_seconds": round(negative_seconds, 3),
        "false_prompts_per_annotated_hour": false_prompts * 3600 / negative_seconds
        if negative_seconds else None,
        "outside_window_seconds": round(sum(r["outside_window_seconds"] for r in rows), 3),
        "audio_seconds": round(sum(r["audio_seconds"] for r in rows), 3),
    }
