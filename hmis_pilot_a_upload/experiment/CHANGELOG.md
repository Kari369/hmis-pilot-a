# HMIS Pilot A — decision and change log

Every change to the confidence calculation, thresholds, input representation or a
system rule gets an entry in this form:

> **Original approach → observed evidence → reason for change → revised approach**

Bump `version` in `hmis_config.json` with each change, so every logged trial can
be traced to the exact rules that produced it.

---

## 0.3.0-candidate — 2026-11-04 — PROPOSED, NOT ADOPTED (for review with Chioma)

Baseline stays **0.2.0** (`hmis_config.json`). The candidate is
`hmis_config_candidate.json`; run it with `HMIS_CONFIG=hmis_config_candidate.json`.

**Diagnosis of A2 (C-K4M → uncertain 0.4792 instead of incidental):**

| Contribution (weight × feature) | A1 | A2 | A3 |
|---|---|---|---|
| Shape (completion + path_fit) | 0.386 | **0.327** | 0.303 |
| Intent cues (hold + facing) | 0.450 | **0.091** | 0.200 |
| Intensity | 0.110 | 0.062 | 0.066 |
| Total | 0.947 | 0.479 | 0.568 |

1. **Main cause: the score is purely additive.** Shape plus intensity alone can reach
   0.55, so a movement that traces the command path lands in "uncertain" even with no
   sign it was addressed to K-11. This is a logic problem, not a threshold or input
   problem: the wipe is supposed to cross the halt zone, as S2 specifies.
2. **Contributing cause: facing is averaged over the whole window.** It counts the
   0.5 s before and after the wipe, when the operator looked at K-11, so it reads 0.33.
   While the hand is actually moving it is 0.03.

**Candidate (two changes, everything else identical):**
- `facing_scope: "while_moving"`: facing is measured only while the hand is away
  from rest. On its own this moves A2 to 0.4187, still uncertain.
- `intent_gate: {min_intent_cues: 0.3}`: if the mean of hold and facing is below
  0.3, confidence is capped at 0.39 (incidental), with the flag
  `intent_gate:no_intent_cues`. The ungated score is logged as `confidence_before_gate`.

This matches the framework's S2 reasoning ("hold duration required for command
threshold"). No trial ID or label is used.

**Evidence:** run 20261104_230714 (candidate) against 20261104_230625 (baseline), 30 trials
each. Candidate: A1 deliberate 0.9467 10/10; A2 incidental 0.39 10/10 (before gate
0.4187), continue_mission with no clarification, K-11 moved 2.86 m; A3 uncertain
0.5680 10/10. Baseline unchanged.

**Limits, to state honestly:**
- The candidate was designed after seeing A2 fail, on the same three conditions.
  Its 30/30 is not independent validation.
- The 0.3 gate level reuses the existing `conflict.low` value; it was not fitted.
- Untested risk: a real command given while not facing K-11 and without a hold
  would be gated to incidental (a false negative). Held-out conditions such as S8 and
  a turned-away command must test this before adoption.

**Also changed (wording only):** S1's on-screen and log text now says "stopped at the
marked site. Extraction authorised" instead of "beginning extraction". K-11 only stops
and turns its beacon green; no extraction behaviour is simulated.

## v0.2.0 — 2026-11-04 — scenario stories, S1 hold, operator reply

**1. Stories (no effect on HMIS input).** Each condition now plays a story around its
signal window (`experiment/stories.json`), adapted from framework scenarios S1–S3 to one
shared quarry site:
- S1: K-11 approaches a marked extraction site; the operator raises and holds a fist,
  with a radio line shown as text.
- S2: dust blows off the quarry face; the operator turns away and wipes their face.
- S3: K-11 passes a boulder; the operator starts a halt, then lowers it.

Captions describe only what can be seen. Story cues go to the operator figure on
channel 3, which HMIS does not receive. Props (cone gate, flag, route boulder) are
present in every trial; the dust is visual only.
*Reason:* the operator's movement needed a believable cause (Kari's request).

**2. Input design: S1 hold 1.3 s → 2.0 s; lead-in 1.0 s → 3.0 s.**
*Original:* C-7Q2 held the fist for 1.3 s; the signal window opened 1 s into each trial.
*Reason:* framework S1 specifies a fist held 2 s, and the stories need time before
the window. *Effect:* C-7Q2 confidence 0.9371 → 0.9467 (intensity 0.67 → 0.74, still
deliberate). C-K4M and C-R9T are unchanged (0.4792, 0.5680).

**3. Rule change: clarification is resolved by the operator's reply (config 0.1.0 → 0.2.0).**
*Original:* after "hold and request clarification", K-11 always resumed after 2 s.
*Revised:* the operator's reply resolves it:
- "confirm" → execute the command
- "continue" → resume the mission
- no reply within 2 s → resume

The reply arrives after classification and never changes the score or class. In
Pilot A the reply is scripted per story (S1 confirm, S2 and S3 continue).
*Reason:* framework S3 requires a clarification prompt and an operator follow-up
that produce a resolved action.
*Evidence:* run 20261104_213508 (30 trials). Classifications match the 0.1.0 runs.
C-K4M and C-R9T resolve as reply "continue" → continue_mission 10/10; K-11 resumes
after 1 s instead of 2 s (1.93 m moved vs 0.97 m). The K-11 beacon shows the state:
green = executing, flashing amber = asking.

## Environment change — 2026-11-03 — field site (HMIS rules unchanged, still 0.1.0)

**Original:** flat 10 m arena with a Pioneer 3-DX and no visible operator.
**Change:**
- generated field site (uneven terrain with potholes, ridges, trees and boulders)
- K-11 is now a Clearpath Moose
- an animated operator figure acts out each signal
- trials reset K-11 to a recorded, settled start pose

**Reason:** a believable field setting for observers and the reviewers.
**Evidence that Pilot A is unaffected:** run 20261103_113236 gave identical
classifications and confidences to run 20261103_101849 (30/30 trials). K-11 drives
2.91 m during each window. After a deliberate halt it moves 0.05 m (coasting); after
an uncertain hold it moves 0.97 m (resumes after the 2 s clarification timeout).
Physical motion is identical across repeats.

## Evidence — run 20261103_101849 (config 0.1.0, 3 conditions × 10 fixed-seed repeats)

- Repeatability: all 30 trials gave identical scores per condition (spread 0.0000).
- A1 (C-7Q2): deliberate, 0.9371, 10/10. K-11 halted (moved 0.003 m after decision).
- A3 (C-R9T): uncertain, 0.5680, 10/10. K-11 held 2 s, then resumed.
- A2 (C-K4M): **uncertain, 0.4792, 0/10** (expected incidental). Flagged
  `shape_without_intent_cues` every time. Completion 0.90 and path_fit 0.73 carry it
  above 0.40, even with hold 0.10 and facing 0.33.
- Failure direction: conservative. HMIS asked instead of acting, so there was no unintended halt.
- Open question (no change made yet): is this a threshold problem, a weighting
  problem, or an input-design problem (the wipe follows the halt path closely)?

## v0.1.0 — 2026-11-03 — starting values

**Confidence bands:** 0.00–0.39 incidental, 0.40–0.69 uncertain, 0.70–1.00
deliberate. These are the provisional bands from the Experiment 1 design. They stay
fixed for the initial runs.

**HMIS-visible input (per 50 ms sample):** hand position (x, y) in a 2D gesture
plane, muscle-activation amplitude, and whether the operator is facing the robot.
This is a simplified stand-in for the future armband. Two fields from the
framework's input table are intentionally excluded:
- *Explicit Machine Request*: whether the operator intended a request *is* the
  ground truth. Giving it to HMIS would hand it the answer.
- *Simulated gesture label* as a class name: HMIS must infer which command a
  movement resembles from its shape, not be told.

**Features (each 0–1), computed per command template:**

| Feature | Meaning | Weight |
|---|---|---|
| completion | How far the hand travelled toward the template's end pose | 0.20 |
| path_fit | How closely the movement follows the template's path | 0.20 |
| hold | Time spent at the end pose, relative to 0.5 s | 0.25 |
| facing | Fraction of the window the operator faced the robot | 0.20 |
| intensity | Mean muscle activation while moving | 0.15 |

**Rationale for the weights:** incidental movements can look like commands by shape
alone, which is exactly what scenario A2 tests. Shape features (completion,
path_fit) therefore carry 0.40 in total. Cues that suggest the operator meant
to address the machine (hold, facing) carry 0.45 in total.

**Disclosure:** these weights were chosen with the three Pilot A conditions in view.
A pass on those three conditions shows the pipeline works. It is not yet evidence
that the scoring rule is good. That evidence comes from conditions written after
v0.1.0 was frozen (see README, "Held-out conditions").

**Missing signals:** if a signal is missing for more than 50% of the window, its
feature is dropped, the remaining weights are renormalised, and confidence is capped
at 0.69. A degraded signal can lead HMIS to ask, but never to act.

**Conflicts:** flagged (not resolved) when the shape features are ≥ 0.7 while the
intent cues are ≤ 0.3, or the reverse.

**Responses:** deliberate + safe environment → execute the command; uncertain →
hold and request clarification (resumes after a 2 s timeout, because Pilot A has
no operator reply); incidental → continue the mission.
