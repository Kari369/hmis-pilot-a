"""Operator figure: acts out the trial so it can be watched.

Visualisation only; it never affects HMIS. The receiver listens on all channels:
  channel 1  the samples HMIS receives          -> right arm, facing, head
             the operator's reply to a prompt   -> confirm fist or "carry on" wave
  channel 3  story cues from the runner         -> where the operator looks between signals
  channel 2  HMIS results                       -> ignored

Mapping from the 2D gesture plane to the Pedestrian's joints (approximate):
    y (height)  -> right shoulder elevation (0 = arm down, 1 = overhead)
    x (reach)   -> elbow bend while the arm is raised (small x = hand drawn in toward the head)
    facing      -> body turns toward K-11, or away with the head lowered
"""

import json
import math

from controller import Supervisor

SHOULDER_RANGE_RAD = 2.85
TURN_AWAY_RAD = 1.2
REPLY_S = 1.6

sup = Supervisor()
timestep = int(sup.getBasicTimeStep())
receiver = sup.getDevice("receiver")
receiver.enable(timestep)

me = sup.getSelf()
k11 = sup.getFromDef("HMIS_ROBOT")
rotation = me.getField("rotation")
my_pos = me.getField("translation").getSFVec3f()
joints = {name: me.getField(name) for name in
          ("rightArmAngle", "rightLowerArmAngle", "leftArmAngle", "leftLowerArmAngle", "headAngle")}
reply_anim = None   # (kind, start time) while a reply gesture plays


def yaw_to(x, y):
    return math.atan2(y - my_pos[1], x - my_pos[0])


def yaw_to_robot():
    p = k11.getPosition()
    return yaw_to(p[0], p[1])


def rest():
    for field in joints.values():
        field.setSFFloat(0.0)
    rotation.setSFRotation([0, 0, 1, yaw_to_robot()])


def pose(sample):
    x, y = sample["x"], max(0.0, sample["y"])
    joints["rightArmAngle"].setSFFloat(-SHOULDER_RANGE_RAD * min(1.0, y))
    joints["rightLowerArmAngle"].setSFFloat(-3.0 * max(0.0, 0.45 - x) * min(1.0, 2.0 * y))
    if sample["facing"] is not None:
        rotation.setSFRotation([0, 0, 1, yaw_to_robot() + (0.0 if sample["facing"] else TURN_AWAY_RAD)])
        joints["headAngle"].setSFFloat(0.0 if sample["facing"] else 0.35)


def play_reply(kind, elapsed):
    """confirm: the fist goes up again. continue: left arm waves K-11 along its route."""
    rotation.setSFRotation([0, 0, 1, yaw_to_robot()])
    if kind == "confirm":
        lift = min(1.0, elapsed / 0.4)
        joints["rightArmAngle"].setSFFloat(-SHOULDER_RANGE_RAD * lift)
        joints["rightLowerArmAngle"].setSFFloat(-0.9 * lift)
    else:
        joints["leftArmAngle"].setSFFloat(-1.5)
        joints["leftLowerArmAngle"].setSFFloat(-0.6 - 0.6 * math.sin(elapsed * 9.0))


while sup.step(timestep) != -1:
    now = sup.getTime()
    while receiver.getQueueLength() > 0:
        msg = json.loads(receiver.getString())
        receiver.nextPacket()
        kind = msg.get("type")
        if kind in ("trial_start", "window_end", "trial_end"):
            reply_anim = None
            rest()
        elif kind == "sample":
            pose(msg)
        elif kind == "operator_reply":
            reply_anim = (msg["reply"], now)
        elif msg.get("cue") == "face_robot":
            rotation.setSFRotation([0, 0, 1, yaw_to_robot()])
        elif msg.get("cue") == "look_at":
            rotation.setSFRotation([0, 0, 1, yaw_to(msg["x"], msg["y"])])

    if reply_anim:
        elapsed = now - reply_anim[1]
        if elapsed < REPLY_S:
            play_reply(reply_anim[0], elapsed)
        else:
            reply_anim = None
            rest()
