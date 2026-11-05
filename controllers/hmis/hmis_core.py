"""HMIS intent classification for Pilot A: features -> confidence -> band -> response.

Pure Python with no Webots dependency, so it can also be run offline
(tools/offline_check.py).

Pipeline for one observation window:
  1. For each command template, extract five features in [0, 1] from the raw samples.
  2. Confidence = weighted sum of the features (weights in hmis_config.json).
  3. The template with the highest confidence is the candidate command.
  4. Confidence is mapped to a band: incidental / uncertain / deliberate.
  5. The band (plus the environment check, held constant in Pilot A) selects a response.

Missing signals: a feature whose signal is missing for more than
max_missing_fraction of the window is dropped, the remaining weights are
renormalised and the confidence is capped at the top of the uncertain band.
Degraded evidence can make HMIS ask, but never act.
"""

import math

FEATURES = ("completion", "path_fit", "hold", "facing", "intensity")


def _clip(v):
    return max(0.0, min(1.0, v))


def _distance_to_segment(p, a, b):
    ab = (b[0] - a[0], b[1] - a[1])
    ap = (p[0] - a[0], p[1] - a[1])
    denom = ab[0] ** 2 + ab[1] ** 2
    f = 0.0 if denom == 0 else _clip((ap[0] * ab[0] + ap[1] * ab[1]) / denom)
    closest = (a[0] + f * ab[0], a[1] + f * ab[1])
    return math.dist(p, closest)


def _template_features(samples, active, rest, end, cfg):
    """Shape features of the movement relative to one command template."""
    d = (end[0] - rest[0], end[1] - rest[1])
    d2 = d[0] ** 2 + d[1] ** 2
    completion = max(
        _clip(((s["x"] - rest[0]) * d[0] + (s["y"] - rest[1]) * d[1]) / d2) for s in samples
    )

    mean_dist = sum(_distance_to_segment((s["x"], s["y"]), rest, end) for s in active) / len(active)
    path_fit = _clip(1.0 - mean_dist / cfg["path_tolerance"])

    # Longest continuous dwell at the template's end pose.
    period = samples[1]["t"] - samples[0]["t"] if len(samples) > 1 else 0.0
    longest, run_start = 0.0, None
    for s in samples:
        if math.dist((s["x"], s["y"]), end) <= cfg["end_radius"]:
            run_start = s["t"] if run_start is None else run_start
            longest = max(longest, s["t"] - run_start + period)
        else:
            run_start = None
    hold = _clip(longest / cfg["hold_required_s"])

    return {"completion": completion, "path_fit": path_fit, "hold": hold}


def _signal_feature(values, max_missing_fraction):
    """Mean of a per-sample signal, or None if too much of it is missing."""
    present = [v for v in values if v is not None]
    if not values or len(present) < (1.0 - max_missing_fraction) * len(values):
        return None
    return sum(present) / len(present)


def classify(samples, cfg):
    """Classify one observation window. Returns a dict that is logged as-is."""
    rest = cfg["rest_pose"]
    active = [s for s in samples if math.dist((s["x"], s["y"]), rest) > cfg["rest_radius"]]

    # facing_scope "window": share of the whole window spent facing K-11 (v0.1/v0.2).
    # "while_moving": only while the hand is away from rest, i.e. while the gesture happens.
    facing_samples = active if cfg.get("facing_scope") == "while_moving" and active else samples
    facing = _signal_feature([None if s["facing"] is None else float(s["facing"]) for s in facing_samples],
                             cfg["max_missing_fraction"])
    intensity_raw = _signal_feature([s["amp"] for s in active], cfg["max_missing_fraction"]) if active else 0.0
    intensity = None if intensity_raw is None else _clip(intensity_raw / cfg["intensity_full_scale"])

    if not active:
        # No movement away from rest: nothing to interpret.
        features = {"completion": 0.0, "path_fit": 0.0, "hold": 0.0, "facing": facing, "intensity": 0.0}
        return _finish(cfg, None, features, {}, flags=["no_movement"])

    per_template = {}
    for name, template in cfg["templates"].items():
        feats = _template_features(samples, active, rest, template["end"], cfg)
        feats.update(facing=facing, intensity=intensity)
        per_template[name] = (_score(feats, cfg), feats)

    best = max(per_template, key=lambda n: per_template[n][0][0])
    (_, _), features = per_template[best]
    scores = {name: round(v[0][0], 4) for name, v in per_template.items()}
    return _finish(cfg, best, features, scores)


def _score(features, cfg):
    """Weighted sum over available features; returns (confidence, missing_features)."""
    weights = cfg["weights"]
    missing = [f for f in FEATURES if features[f] is None]
    available = {f: w for f, w in weights.items() if f not in missing}
    total = sum(available.values())
    confidence = sum(w * features[f] for f, w in available.items()) / total if total else 0.0
    if missing:
        confidence = min(confidence, cfg["bands"]["deliberate_min"] - 0.01)
    return confidence, missing


def _band(confidence, cfg):
    if confidence >= cfg["bands"]["deliberate_min"]:
        return "deliberate"
    if confidence >= cfg["bands"]["uncertain_min"]:
        return "uncertain"
    return "incidental"


def _flags(features, cfg):
    """Record conflicting evidence: command-like shape without intent cues, or the reverse."""
    t = cfg["conflict"]
    present = [features[f] for f in ("completion", "path_fit") if features[f] is not None]
    cues = [features[f] for f in ("hold", "facing") if features[f] is not None]
    if not present or not cues:
        return []
    shape, cue = min(present), sum(cues) / len(cues)
    if shape >= t["high"] and cue <= t["low"]:
        return ["conflict:shape_without_intent_cues"]
    if shape <= t["low"] and cue >= t["high"]:
        return ["conflict:intent_cues_without_shape"]
    return []


def environment_permits(command, environment):
    """Pilot A holds the environment constant and safe. This is the seam Pilot B will vary."""
    return environment.get("environmental_risk") == "low" and environment.get("hazard_presence") == "none"


def _finish(cfg, best, features, template_scores, flags=None):
    confidence, missing = _score(features, cfg)
    flags = list(flags or []) + _flags(features, cfg)
    if missing:
        flags.append("degraded_signal:confidence_capped")
    # Intent gate (optional): a command-shaped movement with no sign it was addressed to
    # K-11 (no hold at the end pose, not facing it) cannot rise above incidental.
    gate = cfg.get("intent_gate")
    confidence_before_gate = confidence
    if gate:
        cues = [features[f] for f in ("hold", "facing") if features[f] is not None]
        if cues and sum(cues) / len(cues) < gate["min_intent_cues"]:
            confidence = min(confidence, cfg["bands"]["uncertain_min"] - 0.01)
            flags.append("intent_gate:no_intent_cues")
    classification = _band(confidence, cfg)

    if classification == "deliberate":
        if environment_permits(best, cfg["environment"]):
            response = f"execute:{best}"
        else:
            response = "hold:environment_blocks_action"
    elif classification == "uncertain":
        response = "hold:request_clarification"
    else:
        response = "continue_mission"

    return {
        "best_template": best,
        "template_confidences": template_scores,
        "features": {f: (None if v is None else round(v, 4)) for f, v in features.items()},
        "missing_features": missing,
        "confidence": round(confidence, 4),
        "confidence_before_gate": round(confidence_before_gate, 4),
        "classification": classification,
        "response": response,
        "flags": flags,
    }
