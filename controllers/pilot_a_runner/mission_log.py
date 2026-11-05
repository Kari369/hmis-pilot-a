"""Readable mission log: one Markdown file per run, one section per trial.

Each trial is a timestamped trace through the experimental-flow stages:
    scene -> input -> classification -> environment -> action -> feedback
          -> operator response -> resolution -> outcome
followed by automatic observations, the ground truth (joined only after HMIS
decided) and an empty "Observer notes" line for the person watching the run.

The full machine record (raw samples, every number) stays in the run's .jsonl.
"""

STAGE_NAMES = {
    "mission": "Mission",
    "scene": "Scene",
    "input": "Input",
    "classification": "Classification",
    "environment": "Environment",
    "action": "Action",
    "feedback": "Feedback",
    "operator_response": "Operator response",
    "resolution": "Resolution",
    "outcome": "Outcome",
}


def _final_action(record):
    resolution = record.get("hmis_resolution") or {}
    return resolution.get("resolved_action") or (record.get("hmis_result") or {}).get("response")


def observations(record, first_of_condition):
    """Things worth a second look, derived from the record. Not a judgement of the design."""
    notes = []
    result = record.get("hmis_result") or {}
    label, expected = record.get("ground_truth_label"), record.get("expected_classification")
    final = _final_action(record) or ""
    if record.get("runner_error"):
        notes.append(f"Runner error: {record['runner_error']}.")
    if expected and result.get("classification") != expected:
        notes.append(f"Misclassified: HMIS output {result.get('classification')}, expected {expected}.")
    if label != "deliberate" and final.startswith("execute"):
        notes.append("False positive: K-11 acted on input that was not a command.")
    if label == "deliberate" and not final.startswith("execute"):
        notes.append("False negative: a real command was not carried out.")
    if label == "incidental" and result.get("response", "").startswith("hold"):
        notes.append("Conservative error: HMIS asked about an incidental movement instead of setting it aside.")
    for flag in result.get("flags", []):
        notes.append(f"Flag raised: {flag}.")
    if result.get("missing_features"):
        notes.append(f"Degraded signal; features dropped: {', '.join(result['missing_features'])}.")
    if first_of_condition is not None and first_of_condition is not record:
        a, b = first_of_condition.get("hmis_result") or {}, result
        same = (a.get("confidence") == b.get("confidence")
                and first_of_condition["displacement_after_window_m"] == record["displacement_after_window_m"])
        notes.append(f"Repeatability: {'identical to' if same else 'DIFFERS from'} "
                     f"{first_of_condition['trial_id']} (confidence and movement).")
    return notes or ["Nothing unusual."]


def write(path, run_meta, records, stories):
    first = {}
    for r in records:
        first.setdefault(r["condition_id"], r)

    lines = [
        f"# Mission log: run {run_meta['run_id']}",
        "",
        f"- HMIS config: {(records[0].get('hmis_result') or {}).get('config_version')} · "
        f"trials: {len(records)} · seed mode: {run_meta['protocol']['seed_mode']} · "
        f"time step: {run_meta['basic_time_step_ms']} ms",
        f"- Signal window: {run_meta['protocol']['window_s']:g} s, opening {run_meta['protocol']['lead_in_s']:g} s "
        f"into each trial. Times below are seconds from trial start.",
        "- Ground truth is shown per trial but was joined only after HMIS had decided.",
        "",
        "## Summary",
        "",
        "| Condition | Scenario | Truth | HMIS output | Final action | Correct |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for cid, r in first.items():
        group = [x for x in records if x["condition_id"] == cid]
        correct = sum(1 for x in group if x.get("correct"))
        lines.append(f"| {cid} | {(stories.get(cid) or {}).get('framework_scenario', '')} | "
                     f"{r.get('ground_truth_label')} | {(r.get('hmis_result') or {}).get('classification')} | "
                     f"{_final_action(r)} | {correct}/{len(group)} |")

    for r in records:
        result = r.get("hmis_result") or {}
        lines += [
            "",
            f"## Trial {r['trial_id']}",
            "",
            "| t (s) | Stage | Event |",
            "| --- | --- | --- |",
        ]
        for e in r.get("mission_trace", []):
            event = e["event"].replace("|", "/")
            lines.append(f"| {e['t']:.2f} | {STAGE_NAMES.get(e['stage'], e['stage'])} | {event} |")
        feats = result.get("features") or {}
        if feats:
            lines += ["", "Features: " + ", ".join(f"{k} {v}" for k, v in feats.items())]
        lines += ["", "Observations:"]
        lines += [f"- {n}" for n in observations(r, first.get(r["condition_id"]))]
        verdict = {True: "correct", False: "incorrect"}.get(r.get("correct"), "n/a")
        lines += [
            "",
            f"Ground truth (joined after the decision): {r.get('ground_truth_label')} "
            f"({r.get('ground_truth_scenario')}); expected {r.get('expected_classification')}; {verdict}.",
            "",
            "Observer notes: ",
        ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
