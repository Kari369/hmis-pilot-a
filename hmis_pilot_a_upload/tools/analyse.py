"""Summarise a Pilot A run log.

Usage:
    python tools/analyse.py                 # latest run in logs/
    python tools/analyse.py logs/run_X.jsonl

Prints, per condition: classifications, confidence range, repeatability
(whether identical repeats gave identical scores) and agreement with ground truth.
Then a confusion matrix of ground-truth label vs HMIS classification.
"""

import glob
import json
import os
import sys
from collections import Counter, defaultdict

PROJECT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def load(path):
    meta, trials = None, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["type"] == "run_meta":
                meta = row
            else:
                trials.append(row)
    return meta, trials


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        runs = sorted(glob.glob(os.path.join(PROJECT, "logs", "run_*.jsonl")))
        if not runs:
            sys.exit("No runs found in logs/. Run the Webots world first.")
        path = runs[-1]

    meta, trials = load(path)
    print(f"Run {meta['run_id']}  ({len(trials)} trials, seed_mode={meta['protocol']['seed_mode']})")
    versions = {(t.get("hmis_result") or {}).get("config_version") for t in trials}
    print(f"HMIS config version(s): {', '.join(sorted(str(v) for v in versions))}\n")

    by_condition = defaultdict(list)
    for t in trials:
        by_condition[t["condition_id"]].append(t)

    for cid, rows in by_condition.items():
        results = [r.get("hmis_result") or {} for r in rows]
        scores = [r.get("confidence") for r in results]
        valid = [s for s in scores if s is not None]
        classes = Counter(r.get("classification") for r in results)
        correct = sum(1 for r in rows if r.get("correct"))
        print(f"{cid}  [{rows[0].get('ground_truth_scenario')}, truth={rows[0].get('ground_truth_label')}, "
              f"expected={rows[0].get('expected_classification')}]")
        print(f"  classifications : {dict(classes)}")
        if valid:
            print(f"  confidence      : min={min(valid):.4f} max={max(valid):.4f} spread={max(valid) - min(valid):.4f}")
        print(f"  identical scores: {'yes' if len(set(scores)) == 1 else 'NO'}")
        print(f"  correct         : {correct}/{len(rows)}")
        flags = Counter(f for r in results for f in r.get("flags", []))
        if flags:
            print(f"  flags           : {dict(flags)}")
        moved = [r["displacement_after_window_m"] for r in rows]
        print(f"  moved after decision (m): min={min(moved):.3f} max={max(moved):.3f}")
        errors = [r["runner_error"] for r in rows if r.get("runner_error")]
        if errors:
            print(f"  runner errors   : {len(errors)} ({errors[0]})")
        print()

    labels = ["deliberate", "incidental", "ambiguous"]
    outputs = ["deliberate", "uncertain", "incidental"]
    matrix = Counter((t.get("ground_truth_label"), (t.get("hmis_result") or {}).get("classification")) for t in trials)
    print("Confusion matrix (rows = ground truth, columns = HMIS output)")
    print(f"{'':>12}" + "".join(f"{o:>12}" for o in outputs))
    for label in labels:
        print(f"{label:>12}" + "".join(f"{matrix[(label, o)]:>12}" for o in outputs))


main()
