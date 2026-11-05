"""Run the classification logic on every condition without Webots.

Usage:
    python tools/offline_check.py

Useful for quick iteration on hmis_config.json before a full Webots run. It does
not read ground_truth.json, so its output can be inspected without seeing the
labels. Webots runs remain the experimental record.
"""

import json
import os
import sys

PROJECT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(PROJECT, "controllers", "hmis"))
sys.path.insert(0, os.path.join(PROJECT, "controllers", "pilot_a_runner"))

import hmis_core  # noqa: E402
import operator_sim  # noqa: E402


def main():
    with open(os.path.join(PROJECT, "experiment", "trials.json"), encoding="utf-8") as f:
        trials = json.load(f)
    config_name = os.environ.get("HMIS_CONFIG", "hmis_config.json")
    with open(os.path.join(PROJECT, "experiment", config_name), encoding="utf-8") as f:
        cfg = json.load(f)
    protocol = trials["protocol"]

    print(f"HMIS config {cfg['version']}\n")
    for condition in trials["conditions"]:
        samples = operator_sim.generate(condition, protocol["window_s"], protocol["sample_period_s"],
                                        condition["seed"])
        result = hmis_core.classify(samples, cfg)
        print(f"{condition['condition_id']}: {result['classification']:<10} conf={result['confidence']:.4f}  "
              f"template={result['best_template']}  response={result['response']}")
        print(f"    features={result['features']}")
        if result["flags"]:
            print(f"    flags={result['flags']}")


main()
