"""HMIS controller for K-11 (Pilot A).

Runs the fixed mission (drive forward) and listens on the radio link for the
operator signal stream. At the end of each observation window it classifies the
input with hmis_core, acts on the result and reports back to the runner.

Its only knowledge of the trial is the stream of samples it receives, plus the
operator's reply if it asked for clarification. The reply arrives after the
classification is made and never changes it: it only resolves what K-11 does next.
It reads experiment/hmis_config.json and nothing else from the experiment folder.

Beacon on K-11: off = on mission, green = executing a command, flashing amber =
asking the operator.
"""

import hashlib
import json
import os
import time

from controller import Robot

import hmis_core

HERE = os.path.dirname(os.path.abspath(__file__))
# HMIS_CONFIG selects another config file in experiment/ (e.g. a candidate under review).
CONFIG_PATH = os.path.normpath(os.path.join(HERE, "..", "..", "experiment",
                                            os.environ.get("HMIS_CONFIG", "hmis_config.json")))


def main():
    with open(CONFIG_PATH, "rb") as f:
        raw = f.read()
    cfg = json.loads(raw)
    config_sha256 = hashlib.sha256(raw).hexdigest()

    robot = Robot()
    timestep = int(robot.getBasicTimeStep())
    # K-11 is a Clearpath Moose: four driven wheels per side.
    motors = [robot.getDevice(f"{side} motor {i}") for side in ("left", "right") for i in range(1, 5)]
    for motor in motors:
        motor.setPosition(float("inf"))
        motor.setVelocity(0.0)
    receiver = robot.getDevice("receiver")
    receiver.enable(timestep)
    emitter = robot.getDevice("emitter")
    beacon = robot.getDevice("beacon")
    BEACON_OFF, BEACON_GREEN, BEACON_AMBER = 0, 1, 2

    mission_speed = cfg["mission"]["wheel_speed_rad_s"]
    samples, trial_id = [], None
    mode, hold_until, pending_command = "idle", 0.0, None

    def resolve(reply, resolved_action, now):
        emitter.send(json.dumps({
            "type": "resolution",
            "trial_id": trial_id,
            "reply": reply,
            "resolved_action": resolved_action,
            "sim_time": round(now, 4),
        }))

    def drive(speed):
        for motor in motors:
            motor.setVelocity(speed)

    while robot.step(timestep) != -1:
        now = robot.getTime()

        while receiver.getQueueLength() > 0:
            msg = json.loads(receiver.getString())
            receiver.nextPacket()
            kind = msg["type"]

            if kind == "trial_start":
                trial_id, samples, mode = msg["trial_id"], [], "mission"
            elif kind == "sample":
                samples.append({k: msg[k] for k in ("t", "x", "y", "amp", "facing")})
            elif kind == "window_end":
                started = time.perf_counter()
                result = hmis_core.classify(samples, cfg)
                compute_ms = (time.perf_counter() - started) * 1000.0

                response = result["response"]
                if response == "execute:halt":
                    mode = "halted"
                elif response == "hold:request_clarification":
                    mode, hold_until = "asking", now + cfg["clarification_timeout_s"]
                    pending_command = result["best_template"]
                elif response.startswith("hold:"):
                    mode, hold_until, pending_command = "holding", now + cfg["clarification_timeout_s"], None
                # execute:advance and continue_mission keep the mission running.

                emitter.send(json.dumps({
                    "type": "result",
                    "trial_id": trial_id,
                    "decision_sim_time": round(now, 4),
                    "compute_ms": round(compute_ms, 3),
                    "config_version": cfg["version"],
                    "config_sha256": config_sha256,
                    "samples_received": len(samples),
                    "environment": cfg["environment"],
                    "mission": {k: cfg["mission"][k] for k in ("primary_objective", "current_task", "machine", "status")},
                    **result,
                }))
            elif kind == "operator_reply" and mode == "asking":
                if msg["reply"] == "confirm" and pending_command == "halt":
                    mode, action = "halted", "execute:halt"
                else:
                    mode, action = "mission", "continue_mission"
                resolve(msg["reply"], action, now)
            elif kind == "trial_end":
                mode, pending_command = "idle", None

        # With no reply before the timeout, the mission resumes.
        if mode in ("asking", "holding") and now >= hold_until:
            if mode == "asking":
                resolve(None, "continue_mission", now)
            mode = "mission"

        drive(mission_speed if mode == "mission" else 0.0)
        if mode == "halted":
            beacon.set(BEACON_GREEN)
        elif mode in ("asking", "holding"):
            beacon.set(BEACON_AMBER if int(now * 4) % 2 == 0 else BEACON_OFF)
        else:
            beacon.set(BEACON_OFF)


main()
