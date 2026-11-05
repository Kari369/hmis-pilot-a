"""Exploratory stress test of the Pilot A classifier, run without Webots.

Usage:
    python tools/stress_test.py

1. Noise robustness: each condition with 200 random seeds at three noise levels.
2. New conditions: seven extra movements with labels written for this probe.

Caution: the probe conditions were written by someone who had already seen
hmis_config.json, so they are NOT held-out evidence. They point to what the
held-out conditions should test. It reads the project and writes nothing.
"""
import collections, json, os, sys

PROJECT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(PROJECT, "controllers", "hmis"))
sys.path.insert(0, os.path.join(PROJECT, "controllers", "pilot_a_runner"))
import hmis_core, operator_sim  # noqa: E402

def load(name):
    with open(os.path.join(PROJECT, "experiment", name), encoding="utf-8") as f:
        return json.load(f)

trials = load("trials.json")
P = trials["protocol"]
configs = {"v0.2.0 (baseline)": load("hmis_config.json"), "v0.3.0-candidate": load("hmis_config_candidate.json")}
truth = {"C-7Q2": "deliberate", "C-K4M": "incidental", "C-R9T": "uncertain"}

def run(cond, cfg, seed):
    return hmis_core.classify(operator_sim.generate(cond, P["window_s"], P["sample_period_s"], seed), cfg)

print("=== 1. Noise robustness: 200 random seeds per condition ===")
for cname, cfg in configs.items():
    print(f"\n[{cname}]")
    for sigma in (0.02, 0.05, 0.08):
        for cond in trials["conditions"]:
            c = dict(cond, noise_sigma=sigma)
            out = collections.Counter(run(c, cfg, s)["classification"] for s in range(200))
            ok = out[truth[cond["condition_id"]]]
            print(f"  sigma={sigma:.2f} {cond['condition_id']} expect {truth[cond['condition_id']]:<10} -> "
                  f"{dict(out)}  correct {ok}/200")

# New conditions, written by me for this test (NOT independent held-out data: I have seen the config).
new = [
    ("fast sloppy genuine halt", "deliberate",
     {"keyframes": [[0, 0, 0, .1], [.2, 0, 0, .1], [.5, .2, .9, .9], [1.3, .15, .92, .85], [1.5, .1, .5, .5], [3, 0, 0, .1]],
      "facing_intervals": [[0, 3]]}),
    ("stretch ending overhead, facing robot", "incidental",
     {"keyframes": [[0, 0, 0, .1], [.4, 0, 0, .1], [1.0, .05, 1.0, .6], [2.2, .05, 1.0, .6], [2.8, 0, 0, .1], [3, 0, 0, .1]],
      "facing_intervals": [[0, 3]]}),
    ("stumble: sudden jerk through halt zone", "incidental",
     {"keyframes": [[0, 0, 0, .1], [1.0, 0, 0, .1], [1.15, .1, .95, .9], [1.35, .3, .2, .7], [1.6, 0, 0, .2], [3, 0, 0, .1]],
      "facing_intervals": [[0, 3]]}),
    ("weak, tired but genuine halt (S8)", "deliberate",
     {"keyframes": [[0, 0, 0, .05], [.3, 0, 0, .05], [1.1, .08, .8, .25], [2.6, .08, .8, .25], [3, .05, .6, .2]],
      "facing_intervals": [[0, 3]]}),
    ("genuine halt, facing signal drops out", "deliberate",
     {"keyframes": [[0, 0, 0, .1], [.3, 0, 0, .1], [.9, .1, 1, .8], [2.9, .1, 1, .8], [3, .08, .85, .7]],
      "facing_intervals": [[0, 3]], "facing_missing_intervals": [[0.5, 3]]}),
    ("genuine halt while turned away", "deliberate",
     {"keyframes": [[0, 0, 0, .1], [.3, 0, 0, .1], [.9, .1, 1, .8], [2.9, .1, 1, .8], [3, .08, .85, .7]],
      "facing_intervals": []}),
    ("no movement at all", "incidental",
     {"keyframes": [[0, 0, 0, .1], [3, 0, 0, .1]], "facing_intervals": [[0, 3]]}),
]
print("\n=== 2. New conditions (my labels; 100 seeds, sigma 0.02) ===")
for cname, cfg in configs.items():
    print(f"\n[{cname}]")
    for name, expect, spec in new:
        cond = dict(spec, condition_id="X", noise_sigma=0.02)
        res = [run(cond, cfg, s) for s in range(100)]
        out = collections.Counter(r["classification"] for r in res)
        confs = [r["confidence"] for r in res]
        print(f"  {name:<40} expect {expect:<10} -> {dict(out)}  conf {min(confs):.2f}-{max(confs):.2f}")
