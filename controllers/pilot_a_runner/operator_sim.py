"""Simulated operator: turns a condition definition into the raw signal stream HMIS receives.

This stands in for the future armband (intent capture interface). It produces only
observable quantities, sampled at a fixed period:

    t       seconds since input onset
    x, y    hand position in a 2D gesture plane (x = forward reach, y = height),
            rest pose is (0, 0); both roughly in [0, 1]
    amp     muscle-activation amplitude in [0, 1] (EMG-like)
    facing  True / False if the operator is facing the robot, None if the signal is missing

Nothing in the output says what the operator meant. The ground-truth label for a
condition lives in experiment/ground_truth.json and is never read here.
"""

import random


def _interpolate(keyframes, t):
    """Linear interpolation over keyframes [[t, x, y, amp], ...] sorted by t."""
    if t <= keyframes[0][0]:
        return keyframes[0][1:]
    for (t0, *v0), (t1, *v1) in zip(keyframes, keyframes[1:]):
        if t0 <= t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return [a + (b - a) * f for a, b in zip(v0, v1)]
    return keyframes[-1][1:]


def _in_intervals(t, intervals):
    return any(start <= t <= end for start, end in intervals)


def generate(condition, window_s, sample_period_s, seed):
    """Return the list of samples for one trial of a condition."""
    rng = random.Random(seed)
    sigma = condition.get("noise_sigma", 0.0)
    keyframes = sorted(condition["keyframes"])
    facing = condition.get("facing_intervals", [])
    facing_missing = condition.get("facing_missing_intervals", [])
    amp_missing = condition.get("amp_missing_intervals", [])

    samples = []
    n = int(round(window_s / sample_period_s))
    for i in range(n + 1):
        t = round(i * sample_period_s, 6)
        x, y, amp = _interpolate(keyframes, t)
        x += rng.gauss(0.0, sigma)
        y += rng.gauss(0.0, sigma)
        amp = min(1.0, max(0.0, amp + rng.gauss(0.0, sigma)))
        samples.append({
            "t": t,
            "x": round(x, 4),
            "y": round(y, 4),
            "amp": None if _in_intervals(t, amp_missing) else round(amp, 4),
            "facing": None if _in_intervals(t, facing_missing) else _in_intervals(t, facing),
        })
    return samples
