"""Pilot A experiment runner (Webots supervisor).

The runner is the experimenter. It:
  1. loads the conditions from experiment/trials.json and their stories from
     experiment/stories.json,
  2. resets K-11 to the same start pose for every trial,
  3. plays the story around the signal window (captions, operator cues, dust),
  4. streams the simulated operator signal to K-11 (the HMIS controller),
  5. receives HMIS's classification, score and response,
  6. if HMIS asks for clarification, sends the operator's scripted reply,
  7. measures what the robot physically did afterwards,
  8. only then joins the hidden ground-truth label and writes the trial record.

The HMIS controller runs in a separate process and never sees trials.json,
stories.json or ground_truth.json. Its inputs are the sample stream and, after it
has decided, the operator's reply to its clarification request.

Set the environment variable HMIS_QUIT_WHEN_DONE=1 to close Webots after the last
trial (used for batch runs); otherwise the simulation pauses.
"""

import csv
import hashlib
import json
import math
import os
import time

from controller import Supervisor

import mission_log
import operator_sim

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.normpath(os.path.join(HERE, "..", ".."))
EXPERIMENT_DIR = os.path.join(PROJECT, "experiment")
LOG_DIR = os.path.join(PROJECT, "logs")

RESULT_TIMEOUT_S = 2.0
SETTLE_S = 1.0
DUST_PARKED = [0.0, 0.0, -50.0]

# What a correct HMIS output looks like for each ground-truth label.
EXPECTED_CLASSIFICATION = {
    "deliberate": "deliberate",
    "incidental": "incidental",
    "ambiguous": "uncertain",
}

# On-screen lines. HMIS output is shown as HMIS decided it; nothing here reveals ground truth.
LINE_TRIAL, LINE_STORY, LINE_VERDICT, LINE_K11 = 0, 1, 2, 3
# Dark text, drawn along the bottom of the view where it sits over the light ground.
WHITE, GREY, GREEN, AMBER = 0x111111, 0x4A4A4A, 0x0B6B2C, 0x9A5200
VERDICT_COLORS = {"deliberate": GREEN, "uncertain": AMBER, "incidental": GREY}
RESPONSE_TEXT = {
    # K-11 stops; "extraction authorised" is a simulated mission-state change, no digging is modelled.
    "execute:halt": ("K-11: stopped at the marked site. Extraction authorised.", GREEN),
    "execute:advance": ("K-11: advancing as signalled.", GREEN),
    "hold:request_clarification": ("K-11: \"Stop here? Confirm, or wave me on.\"", AMBER),
    "hold:environment_blocks_action": ("K-11: holding, the environment blocks that action.", AMBER),
    "continue_mission": ("K-11: signal set aside; continuing the survey.", GREY),
}
FEEDBACK_TEXT = {
    "execute:halt": "Lightweight acknowledgment only, no MIF alert: beacon turns green. K-11 stops; "
                    "extraction authorised (simulated state change, no extraction behaviour modelled).",
    "hold:request_clarification": "Clarification prompt (MIF): \"Stop here? Confirm, or wave me on.\" "
                                  "Beacon flashes amber.",
    "continue_mission": "No feedback issued; the signal is logged and set aside.",
}
RESOLUTION_TEXT = {
    "execute:halt": ("K-11: confirmed. Stopped; extraction authorised.", GREEN),
    "continue_mission": ("K-11: understood. Continuing the survey.", GREY),
}


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Runner:
    def __init__(self):
        self.sup = Supervisor()
        self.timestep = int(self.sup.getBasicTimeStep())
        self.emitter = self.sup.getDevice("emitter")              # channel 1: HMIS (+ operator figure)
        self.story_emitter = self.sup.getDevice("story_emitter")  # channel 3: operator figure only
        self.receiver = self.sup.getDevice("receiver")
        self.receiver.enable(self.timestep)
        self.robot = self.sup.getFromDef("HMIS_ROBOT")
        self.dust = self.sup.getFromDef("DUST").getField("translation")
        self.inbox = []
        self.beats, self.trial_t0, self.dust_motion, self.reply_sent = [], 0.0, None, None
        self.mission_trace = []

    def settle_and_save_start(self):
        """Let K-11 settle onto the terrain once, then record that pose as the trial start."""
        self.step_seconds(SETTLE_S)
        self.start_translation = self.robot.getField("translation").getSFVec3f()
        self.start_rotation = self.robot.getField("rotation").getSFRotation()

    def step(self):
        if self.sup.step(self.timestep) == -1:
            raise SystemExit(0)
        while self.receiver.getQueueLength() > 0:
            self.inbox.append(json.loads(self.receiver.getString()))
            self.receiver.nextPacket()
        self.play_story()

    def step_seconds(self, seconds):
        for _ in range(int(round(seconds * 1000 / self.timestep))):
            self.step()

    def send(self, message):
        self.emitter.send(json.dumps(message))

    def trial_time(self):
        return self.sup.getTime() - self.trial_t0

    # Story ---------------------------------------------------------------

    def start_story(self, story):
        self.trial_t0 = self.sup.getTime()
        self.beats = sorted((story or {}).get("beats", []), key=lambda b: b["t"])
        self.dust_motion = None
        self.dust.setSFVec3f(DUST_PARKED)

    def trace(self, stage, event, **data):
        """One timestamped line of the mission log."""
        entry = {"t": round(self.trial_time(), 3), "sim_time": round(self.sup.getTime(), 3),
                 "stage": stage, "event": event}
        if data:
            entry["data"] = data
        self.mission_trace.append(entry)

    def add_beat(self, beat):
        self.beats.append(beat)
        self.beats.sort(key=lambda b: b["t"])

    def play_story(self):
        now = self.trial_time()
        while self.beats and self.beats[0]["t"] <= now:
            beat = self.beats.pop(0)
            if "caption" in beat:
                self.show(LINE_STORY, beat["caption"], WHITE)
            if "operator" in beat:
                self.story_emitter.send(json.dumps(beat["operator"]))
            if "dust" in beat:
                self.dust_motion = {**beat["dust"], "t0": now}
            if "reply" in beat:
                self.send({"type": "operator_reply", "reply": beat["reply"]})
                self.reply_sent = {"reply": beat["reply"], "sim_time": round(self.sup.getTime(), 4)}
                self.trace("operator_response", f"Operator replies: {beat['reply']}. {beat.get('caption', '')}".strip())
            elif "caption" in beat:
                self.trace("scene", beat["caption"])
        if self.dust_motion:
            d = self.dust_motion
            f = (now - d["t0"]) / d["duration_s"]
            if f >= 1.0:
                self.dust.setSFVec3f(DUST_PARKED)
                self.dust_motion = None
            else:
                self.dust.setSFVec3f([a + (b - a) * f for a, b in zip(d["from"], d["to"])])

    # Trial ---------------------------------------------------------------

    def reset_robot(self):
        # Restore the settled start pose. (Node.loadState was tried and left the Moose's
        # wheels unable to drive, so the pose is restored explicitly instead.)
        self.robot.getField("translation").setSFVec3f(self.start_translation)
        self.robot.getField("rotation").setSFRotation(self.start_rotation)
        self.robot.resetPhysics()
        self.step()

    def show(self, line, text, color=WHITE):
        """On-screen text for whoever is watching. Never shows ground truth."""
        self.sup.setLabel(line, text, 0.02, 0.77 + 0.05 * line, 0.075, color, 0.0, "Arial")

    def position(self):
        return self.robot.getPosition()

    def wait_for(self, kind, seconds):
        for _ in range(int(seconds * 1000 / self.timestep)):
            self.step()
            message = next((m for m in self.inbox if m.get("type") == kind), None)
            if message:
                return message
        return None

    def run_trial(self, trial_index, condition, story, repeat, protocol, seed):
        trial_id = f"{condition['condition_id']}#{repeat:02d}"
        window_s = protocol["window_s"]
        period_s = protocol["sample_period_s"]
        samples = operator_sim.generate(condition, window_s, period_s, seed)
        steps_per_sample = int(round(period_s * 1000 / self.timestep))

        self.inbox.clear()
        self.reply_sent = None
        self.reset_robot()
        for line in (LINE_STORY, LINE_VERDICT, LINE_K11):
            self.show(line, "")
        self.show(LINE_TRIAL, f"Trial {trial_id}", GREY)
        self.send({"type": "trial_start", "trial_id": trial_id})
        self.story_emitter.send(json.dumps({"cue": "face_robot"}))
        self.mission_trace = []
        self.start_story(story)
        self.trace("mission", "Trial start. K-11 on survey mission along the haul route.")
        self.step_seconds(protocol["lead_in_s"])

        onset_sim_time = self.sup.getTime()
        pos_at_onset = self.position()
        self.trace("input", f"Signal window opens ({window_s:g} s, a sample every {period_s * 1000:g} ms).")
        for sample in samples:
            self.send({"type": "sample", **sample})
            for _ in range(steps_per_sample):
                self.step()
            snapshot = os.environ.get("HMIS_SNAPSHOT_DIR")
            if snapshot and repeat == 0 and sample["t"] in (0.5, 1.5, 2.5):
                self.sup.exportImage(os.path.join(snapshot, f"{condition['condition_id']}_w{sample['t']}.png"), 90)
        self.send({"type": "window_end"})
        window_end_sim_time = self.sup.getTime()
        pos_at_window_end = self.position()
        facing = [s["facing"] for s in samples if s["facing"] is not None]
        self.trace("input", f"Signal window closes: {len(samples)} samples sent to HMIS.",
                   peak_hand_height=round(max(s["y"] for s in samples), 3),
                   facing_share=round(sum(facing) / len(facing), 3) if facing else None,
                   missing_values=sum(1 for s in samples if s["facing"] is None or s["amp"] is None))

        result = self.wait_for("result", RESULT_TIMEOUT_S)
        decision_trial_time = self.trial_time()
        if result:
            self.trace("classification", f"{result['classification']}, confidence {result['confidence']:.4f} "
                       f"(closest command: {result['best_template']}).",
                       features=result["features"], flags=result["flags"],
                       missing_features=result["missing_features"], compute_ms=result["compute_ms"])
            env = result.get("environment", {})
            self.trace("environment", "Snapshot at decision: " + ", ".join(f"{k} {v}" for k, v in env.items()) + ".",
                       environment=env, mission=result.get("mission"))
            self.trace("action", f"Response selected: {result['response']}.")
            self.trace("feedback", FEEDBACK_TEXT.get(result["response"], "None."))
            self.show(LINE_VERDICT, f"HMIS: {result['classification']}   confidence {result['confidence']:.2f}",
                      VERDICT_COLORS.get(result["classification"], WHITE))
            text, color = RESPONSE_TEXT.get(result["response"], (f"K-11: {result['response']}", WHITE))
            self.show(LINE_K11, text, color)
            asked = result["response"] == "hold:request_clarification"
            if asked and story and story.get("if_asked"):
                reply = story["if_asked"]
                self.add_beat({"t": decision_trial_time + reply["after_s"], "reply": reply["reply"],
                               "caption": reply["caption"]})

        resolution = None
        post_steps = int(round(protocol["post_s"] * 1000 / self.timestep))
        snapshot = os.environ.get("HMIS_SNAPSHOT_DIR")
        for i in range(post_steps):
            self.step()
            if resolution is None:
                resolution = next((m for m in self.inbox if m.get("type") == "resolution"), None)
                if resolution:
                    text, color = RESOLUTION_TEXT.get(resolution["resolved_action"],
                                                      (f"K-11: {resolution['resolved_action']}", WHITE))
                    self.show(LINE_K11, text, color)
                    how = f"reply '{resolution['reply']}'" if resolution["reply"] else "timeout, no reply"
                    self.trace("resolution", f"HMIS resolves the request ({how}): {resolution['resolved_action']}.")
            if snapshot and repeat == 0 and i in (int(post_steps * 0.2), int(post_steps * 0.6)):
                self.sup.exportImage(os.path.join(snapshot, f"{condition['condition_id']}_p{i}.png"), 90)
        pos_after = self.position()
        moved = math.dist(pos_at_window_end[:2], pos_after[:2])
        final = (resolution or {}).get("resolved_action") or (result or {}).get("response", "no decision")
        self.trace("outcome", f"Final action: {final}. K-11 moved {moved:.2f} m in the {protocol['post_s']:g} s "
                   f"after the window closed.")
        self.send({"type": "trial_end"})
        self.beats, self.dust_motion = [], None
        self.dust.setSFVec3f(DUST_PARKED)
        self.step_seconds(0.1)

        record = {
            "trial_index": trial_index,
            "trial_id": trial_id,
            "condition_id": condition["condition_id"],
            "repeat": repeat,
            "seed": seed,
            "onset_sim_time": round(onset_sim_time, 4),
            "window_end_sim_time": round(window_end_sim_time, 4),
            "hmis_visible_samples": samples,
            "hmis_result": result,
            "operator_reply": self.reply_sent,
            "hmis_resolution": resolution,
            "displacement_during_window_m": round(math.dist(pos_at_onset[:2], pos_at_window_end[:2]), 4),
            "displacement_after_window_m": round(math.dist(pos_at_window_end[:2], pos_after[:2]), 4),
            "robot_position_onset": [round(v, 3) for v in pos_at_onset],
            "post_s": protocol["post_s"],
            "mission_trace": self.mission_trace,
            "observer_notes": "",
        }
        if result is None:
            record["runner_error"] = "no result from HMIS within timeout"
        else:
            record["onset_to_decision_s"] = round(result["decision_sim_time"] - onset_sim_time, 4)
        return record


def attach_ground_truth(record, ground_truth):
    """Join the hidden label after HMIS has already decided."""
    truth = ground_truth.get(record["condition_id"], {})
    label = truth.get("label")
    record["ground_truth_label"] = label
    record["ground_truth_scenario"] = truth.get("scenario")
    result = record.get("hmis_result") or {}
    expected = EXPECTED_CLASSIFICATION.get(label)
    record["expected_classification"] = expected
    record["correct"] = (result.get("classification") == expected) if expected else None
    return record


def csv_row(record):
    result = record.get("hmis_result") or {}
    features = result.get("features") or {}
    reply = record.get("operator_reply") or {}
    resolution = record.get("hmis_resolution") or {}
    return {
        "trial_index": record["trial_index"],
        "trial_id": record["trial_id"],
        "condition_id": record["condition_id"],
        "repeat": record["repeat"],
        "seed": record["seed"],
        "best_template": result.get("best_template"),
        "completion": features.get("completion"),
        "path_fit": features.get("path_fit"),
        "hold": features.get("hold"),
        "facing": features.get("facing"),
        "intensity": features.get("intensity"),
        "missing_features": ";".join(result.get("missing_features", [])),
        "flags": ";".join(result.get("flags", [])),
        "confidence": result.get("confidence"),
        "classification": result.get("classification"),
        "response": result.get("response"),
        "operator_reply": reply.get("reply", ""),
        "resolved_action": resolution.get("resolved_action", ""),
        "onset_to_decision_s": record.get("onset_to_decision_s"),
        "compute_ms": result.get("compute_ms"),
        "displacement_after_window_m": record["displacement_after_window_m"],
        "hmis_config_version": result.get("config_version"),
        "ground_truth_label": record["ground_truth_label"],
        "expected_classification": record["expected_classification"],
        "correct": record["correct"],
        "runner_error": record.get("runner_error", ""),
        "observer_notes": "",
    }


def main():
    trials_path = os.path.join(EXPERIMENT_DIR, "trials.json")
    stories_path = os.path.join(EXPERIMENT_DIR, "stories.json")
    with open(trials_path, encoding="utf-8") as f:
        trials = json.load(f)
    with open(stories_path, encoding="utf-8") as f:
        stories = json.load(f)["stories"]
    protocol = trials["protocol"]
    if os.environ.get("HMIS_REPEATS"):
        protocol["repeats"] = int(os.environ["HMIS_REPEATS"])   # quick checks only

    runner = Runner()
    run_id = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(LOG_DIR, exist_ok=True)
    jsonl_path = os.path.join(LOG_DIR, f"run_{run_id}.jsonl")
    csv_path = os.path.join(LOG_DIR, f"run_{run_id}.csv")
    print(f"[runner] run {run_id}: {len(trials['conditions'])} conditions x {protocol['repeats']} repeats")

    runner.settle_and_save_start()

    records = []
    trial_index = 0
    for repeat in range(protocol["repeats"]):
        for condition in trials["conditions"]:
            seed = condition["seed"] if protocol["seed_mode"] == "fixed" else condition["seed"] + repeat
            story = stories.get(condition["condition_id"])
            records.append(runner.run_trial(trial_index, condition, story, repeat, protocol, seed))
            result = records[-1].get("hmis_result") or {}
            resolution = records[-1].get("hmis_resolution") or {}
            print(f"[runner] {records[-1]['trial_id']}: {result.get('classification')} "
                  f"conf={result.get('confidence')} response={result.get('response')}"
                  + (f" -> {resolution.get('resolved_action')}" if resolution else ""))
            trial_index += 1

    # Ground truth is opened only now, after every HMIS decision has been made.
    with open(os.path.join(EXPERIMENT_DIR, "ground_truth.json"), encoding="utf-8") as f:
        ground_truth = json.load(f)["conditions"]

    run_meta = {
        "run_id": run_id,
        "trials_sha256": sha256_of(trials_path),
        "stories_sha256": sha256_of(stories_path),
        "protocol": protocol,
        "basic_time_step_ms": runner.timestep,
    }
    with open(jsonl_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "run_meta", **run_meta}) + "\n")
        for record in records:
            f.write(json.dumps({"type": "trial", "run_id": run_id, **attach_ground_truth(record, ground_truth)}) + "\n")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        rows = [csv_row(r) for r in records]
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    mission_log_path = os.path.join(LOG_DIR, f"run_{run_id}_mission_log.md")
    mission_log.write(mission_log_path, run_meta, records, stories)
    print(f"[runner] wrote {jsonl_path}")
    print(f"[runner] wrote {csv_path}")
    print(f"[runner] wrote {mission_log_path}")

    if os.environ.get("HMIS_QUIT_WHEN_DONE") == "1":
        runner.sup.simulationQuit(0)
    else:
        runner.sup.simulationSetMode(Supervisor.SIMULATION_MODE_PAUSE)
    runner.step()


main()
