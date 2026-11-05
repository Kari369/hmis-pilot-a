"""Generate worlds/pilot_a.wbt: a large uneven field site for HMIS Pilot A.

Usage:
    python tools/build_world.py

The world is generated from a fixed seed, so rebuilding gives an identical world.
Change the constants below to reshape the site, then rebuild.

What it creates:
  - a 160 m x 160 m terrain (ElevationGrid, 1 m resolution) with rolling ground,
    potholes (depressions) and ridges (raised bands)
  - a gentle mission corridor where K-11 drives during trials, so every trial
    crosses the same ground
  - trees and boulders scattered around the site
  - K-11 (Clearpath Moose, 8-wheel field robot) and the operator (Pedestrian)
  - controllers/pilot_a_runner/world_layout.json: start poses the runner uses
"""

import json
import math
import os
import random

PROJECT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
WORLD_PATH = os.path.join(PROJECT, "worlds", "pilot_a.wbt")
LAYOUT_PATH = os.path.join(PROJECT, "controllers", "pilot_a_runner", "world_layout.json")

SEED = 42
SIZE_M = 160            # terrain is SIZE_M x SIZE_M, centred on the origin
SPACING_M = 1.0
ROBOT_START = (0.0, 0.0)            # K-11 starts here, facing +x
CORRIDOR = (-8.0, 16.0, 4.0)        # x_min, x_max, half-width of the gentle mission strip
OPERATOR_POS = (6.0, 4.0)           # operator stands beside the mission line
N_POTHOLES, N_RIDGES, N_TREES, N_ROCKS = 45, 9, 90, 40
SITE_X0, SITE_X1 = 4.8, 7.0         # marked extraction site: cone gate across the route
SITE_FLAG = (5.9, 2.6)
ROUTE_BOULDER = (4.0, -2.5)         # boulder K-11 passes close to (story for the half-formed halt)
CAMERA_EYE = (13.0, 11.0, 4.5)     # initial view: behind the operator, looking over the mission strip
CAMERA_TARGET = (2.5, 0.5, 0.6)

R2025A = "https://raw.githubusercontent.com/cyberbotics/webots/R2025a/projects"
PROTOS = {
    "TexturedBackground": "objects/backgrounds/protos/TexturedBackground.proto",
    "TexturedBackgroundLight": "objects/backgrounds/protos/TexturedBackgroundLight.proto",
    "Soil": "appearances/protos/Soil.proto",
    "Moose": "robots/clearpath/moose/protos/Moose.proto",
    "Pedestrian": "humans/pedestrian/protos/Pedestrian.proto",
    "Oak": "objects/trees/protos/Oak.proto",
    "Pine": "objects/trees/protos/Pine.proto",
    "Sassafras": "objects/trees/protos/Sassafras.proto",
    "Cypress": "objects/trees/protos/Cypress.proto",
    "Rock": "objects/rocks/protos/Rock.proto",
    "TrafficCone": "objects/traffic/protos/TrafficCone.proto",
}


def smoothstep(e0, e1, v):
    t = max(0.0, min(1.0, (v - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def look_at(eye, target):
    """Viewpoint axis-angle rotation so the camera (looking along +x, up +z) faces target."""
    dx, dy, dz = (t - e for t, e in zip(target, eye))
    yaw, pitch = math.atan2(dy, dx), math.atan2(-dz, math.hypot(dx, dy))
    # Quaternion of Rz(yaw) * Ry(pitch), converted to axis-angle.
    cy, sy, cp, sp = math.cos(yaw / 2), math.sin(yaw / 2), math.cos(pitch / 2), math.sin(pitch / 2)
    w, x, y, z = cy * cp, -sy * sp, cy * sp, sy * cp
    angle = 2 * math.acos(max(-1.0, min(1.0, w)))
    s = math.sqrt(max(1e-12, 1 - w * w))
    return f"{x / s:.4f} {y / s:.4f} {z / s:.4f} {angle:.4f}"


def corridor_weight(x, y):
    """1 inside the mission corridor, fading to 0 over 6 m outside it."""
    x0, x1, hw = CORRIDOR
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(abs(y) - hw, 0.0)
    return 1.0 - smoothstep(0.0, 6.0, math.hypot(dx, dy))


def build_height_function(rng):
    waves = [(rng.uniform(0.6, 1.6), rng.uniform(18, 45), rng.uniform(0, math.tau), rng.uniform(0, math.tau))
             for _ in range(6)]
    bumps = [(rng.uniform(0.04, 0.12), rng.uniform(3, 7), rng.uniform(0, math.tau), rng.uniform(0, math.tau))
             for _ in range(5)]

    potholes = []
    while len(potholes) < N_POTHOLES:
        x, y = rng.uniform(-70, 70), rng.uniform(-70, 70)
        if corridor_weight(x, y) == 0.0 and math.dist((x, y), OPERATOR_POS) > 4:
            potholes.append((x, y, rng.uniform(0.8, 2.5), rng.uniform(0.25, 0.7)))
    # A few close to the mission strip so they are visible from the start position.
    potholes += [(4.0, -8.5, 1.8, 0.6), (11.0, 8.5, 2.2, 0.5), (19.0, -3.0, 1.5, 0.45)]

    ridges = []
    for _ in range(N_RIDGES):
        cx, cy = rng.uniform(-60, 60), rng.uniform(-60, 60)
        angle = rng.uniform(0, math.pi)
        ridges.append((cx, cy, angle, rng.uniform(8, 30), rng.uniform(0.8, 2.0), rng.uniform(0.4, 1.1)))
    ridges += [(24.0, 0.0, math.pi / 2, 10.0, 1.5, 0.7), (6.0, -12.0, 0.2, 9.0, 1.2, 0.6)]

    def height(x, y):
        rolling = sum(a * math.sin(x * math.cos(d) / w * math.tau + p) * 0.5 +
                      a * math.cos(y * math.sin(d + 1) / w * math.tau + p) * 0.5 for a, w, d, p in waves)
        fine = sum(a * math.sin(x / w * math.tau + p) * math.cos(y / w * math.tau + q) for a, w, p, q in bumps)
        features = 0.0
        for px, py, r, depth in potholes:
            d2 = (x - px) ** 2 + (y - py) ** 2
            features -= depth * math.exp(-d2 / (r * r))
        for cx, cy, ang, half_len, width, h in ridges:
            ux, uy = math.cos(ang), math.sin(ang)
            along = (x - cx) * ux + (y - cy) * uy
            across = -(x - cx) * uy + (y - cy) * ux
            features += h * math.exp(-(across / width) ** 2) * (1 - smoothstep(half_len - 3, half_len, abs(along)))
        w = corridor_weight(x, y)
        # Inside the corridor: only a gentle slope and small bumps, identical for every trial.
        return (1 - w) * (rolling + fine + features) + w * (0.25 * rolling + 0.4 * fine)

    return height


def main():
    rng = random.Random(SEED)
    height = build_height_function(rng)

    n = int(SIZE_M / SPACING_M) + 1
    origin = -SIZE_M / 2
    grid = [[height(origin + i * SPACING_M, origin + j * SPACING_M) for i in range(n)] for j in range(n)]
    base = grid[int(-origin / SPACING_M)][int(-origin / SPACING_M)]
    grid = [[h - base for h in row] for row in grid]   # start position sits at z = 0

    def ground(x, y):
        """Bilinear height of the grid, which is what the physics sees."""
        fx, fy = (x - origin) / SPACING_M, (y - origin) / SPACING_M
        i, j = min(int(fx), n - 2), min(int(fy), n - 2)
        tx, ty = fx - i, fy - j
        return ((1 - tx) * (1 - ty) * grid[j][i] + tx * (1 - ty) * grid[j][i + 1] +
                (1 - tx) * ty * grid[j + 1][i] + tx * ty * grid[j + 1][i + 1])

    def free_spot(min_r, max_r, clearance):
        while True:
            a, r = rng.uniform(0, math.tau), rng.uniform(min_r, max_r)
            x, y = ROBOT_START[0] + 6 + r * math.cos(a), r * math.sin(a)
            if corridor_weight(x, y) < 0.05 and math.dist((x, y), OPERATOR_POS) > clearance:
                return x, y

    heights = " ".join(f"{h:.3f}" for row in grid for h in row)
    out = [
        "#VRML_SIM R2025a utf8",
        "",
        *[f'EXTERNPROTO "{R2025A}/{path}"' for path in PROTOS.values()],
        "",
        "WorldInfo {",
        '  info [ "HMIS Experiment 1, Pilot A: intent classification at a field site." '
        '"Generated by tools/build_world.py. Do not edit by hand; change the generator and rebuild." ]',
        '  title "HMIS Pilot A"',
        "  CFM 0.0003",
        "  ERP 0.4",
        "  basicTimeStep 5",
        "  randomSeed 0",
        "}",
        "Viewpoint {",
        f"  orientation {look_at(CAMERA_EYE, CAMERA_TARGET)}",
        f"  position {CAMERA_EYE[0]} {CAMERA_EYE[1]} {CAMERA_EYE[2]}",
        "  near 0.5",
        "}",
        'TexturedBackground { texture "noon_cloudy_countryside" }',
        "TexturedBackgroundLight { luminosity 1.1 }",
        "Fog { color 0.78 0.82 0.86 visibilityRange 220 }",
        "DEF TERRAIN Solid {",
        f"  translation {origin} {origin} 0",
        "  children [",
        "    Shape {",
        f'      appearance Soil {{ type "braun" textureTransform TextureTransform {{ scale {SIZE_M / 4} {SIZE_M / 4} }} }}',
        "      geometry DEF TERRAIN_GRID ElevationGrid {",
        f"        xDimension {n} xSpacing {SPACING_M} yDimension {n} ySpacing {SPACING_M}",
        f"        height [ {heights} ]",
        "      }",
        "      castShadows FALSE",
        "    }",
        "  ]",
        '  name "terrain"',
        "  boundingObject USE TERRAIN_GRID",
        "}",
    ]

    tree_types = ["Oak", "Pine", "Sassafras", "Cypress"]
    for k in range(N_TREES):
        x, y = free_spot(9, 75, 6)
        kind = tree_types[k % len(tree_types)]
        out.append(f'{kind} {{ translation {x:.2f} {y:.2f} {ground(x, y) - 0.1:.3f} '
                   f'rotation 0 0 1 {rng.uniform(0, math.tau):.3f} name "{kind.lower()} {k}" }}')
    for k in range(N_ROCKS):
        x, y = free_spot(7, 60, 4)
        out.append(f'Rock {{ translation {x:.2f} {y:.2f} {ground(x, y) - 0.05:.3f} '
                   f'rotation 0 0 1 {rng.uniform(0, math.tau):.3f} name "boulder {k}" '
                   f'type "{rng.choice(["regular", "flat"])}" scale {rng.uniform(3, 9):.2f} }}')

    # Story props. Identical in every trial: the environment stays constant for Pilot A.
    # Marked extraction site: a cone gate across K-11's route, with a flag beside the operator.
    for k, (x, y) in enumerate([(SITE_X0, -1.8), (SITE_X0, 1.8), (SITE_X1, -1.8), (SITE_X1, 1.8)]):
        out.append(f'TrafficCone {{ translation {x} {y} {ground(x, y):.3f} name "site cone {k}" }}')
    fx, fy = SITE_FLAG
    out += [
        f"Pose {{ translation {fx} {fy} {ground(fx, fy):.3f} children [",
        "  Shape { appearance PBRAppearance { baseColor 0.85 0.85 0.85 roughness 0.6 metalness 0 }"
        " geometry Cylinder { height 2.2 radius 0.03 } }",
        "  Pose { translation 0.3 0 1.0 children [ Shape { appearance PBRAppearance { baseColor 1 0.4 0.05"
        " roughness 0.8 metalness 0 } geometry Box { size 0.55 0.02 0.35 } } ] }",
        "] }",
    ]
    bx, by = ROUTE_BOULDER
    out.append(f'Rock {{ translation {bx} {by} {ground(bx, by) - 0.05:.3f} name "route boulder" scale 7 }}')
    # Dust cloud, parked underground until the runner moves it through a scene.
    rng_dust = random.Random(SEED + 1)
    puffs = [(rng_dust.uniform(-2.5, 2.5), rng_dust.uniform(-2.5, 2.5), rng_dust.uniform(-0.8, 0.9),
              rng_dust.uniform(0.3, 0.75)) for _ in range(26)]
    out.append("DEF DUST Pose { translation 0 0 -50 children [")
    for px, py, pz, r in puffs:
        out.append(f"  Pose {{ translation {px:.2f} {py:.2f} {pz:.2f} children [ Shape {{ appearance PBRAppearance "
                   f"{{ baseColor 0.8 0.72 0.6 roughness 1 metalness 0 transparency 0.82 }} "
                   f"geometry Sphere {{ radius {r:.2f} subdivision 2 }} castShadows FALSE }} ] }}")
    out.append("] }")

    robot_z = ground(*ROBOT_START) + 0.45
    out += [
        "DEF HMIS_ROBOT Moose {",
        f"  translation {ROBOT_START[0]} {ROBOT_START[1]} {robot_z:.3f}",
        '  name "K-11"',
        '  controller "hmis"',
        "  color 0.9 0.55 0.1",
        "  bodySlot [",
        '    Receiver { name "receiver" channel 1 }',
        '    Emitter { name "emitter" channel 2 }',
        # Status beacon: green = executing a command, flashing amber = asking the operator.
        "    Pose { translation 0.85 0 0.42 children [ LED { name \"beacon\" color [ 0.1 0.95 0.2, 1 0.65 0 ]"
        " children [ Shape { appearance PBRAppearance { baseColor 0.25 0.25 0.25 roughness 0.3 metalness 0 }"
        " geometry Cylinder { height 0.14 radius 0.08 } } ] } ] }",
        "  ]",
        "}",
    ]

    op_z = ground(*OPERATOR_POS) + 1.27
    op_yaw = math.atan2(ROBOT_START[1] - OPERATOR_POS[1], ROBOT_START[0] - OPERATOR_POS[0])
    out += [
        "DEF OPERATOR Pedestrian {",
        f"  translation {OPERATOR_POS[0]} {OPERATOR_POS[1]} {op_z:.3f}",
        f"  rotation 0 0 1 {op_yaw:.4f}",
        '  name "operator"',
        '  controller "operator_figure"',
        # Pedestrian.proto only builds movable joints (and runs the controller) when controllerArgs is non-empty.
        '  controllerArgs [ "--animated" ]',
        "  shirtColor 0.95 0.45 0.05",
        "  pantsColor 0.15 0.18 0.25",
        # Channel -1: the operator hears the HMIS signal stream (1) and the story cues (3).
        '  bodySlot [ Receiver { name "receiver" channel -1 } ]',
        "}",
        "Robot {",
        '  name "pilot_a_runner"',
        '  controller "pilot_a_runner"',
        "  supervisor TRUE",
        "  children [",
        '    Emitter { name "emitter" channel 1 }',
        '    Emitter { name "story_emitter" channel 3 }',
        '    Receiver { name "receiver" channel 2 }',
        "  ]",
        "}",
    ]

    with open(WORLD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    with open(LAYOUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "robot_start_translation": [ROBOT_START[0], ROBOT_START[1], round(robot_z, 4)],
            "robot_start_rotation": [0, 0, 1, 0],
            "operator_translation": [OPERATOR_POS[0], OPERATOR_POS[1], round(op_z, 4)],
            "operator_ground_z": round(ground(*OPERATOR_POS), 4),
        }, f, indent=2)
    print(f"wrote {WORLD_PATH} ({n}x{n} terrain, {N_TREES} trees, {N_ROCKS} boulders)")
    print(f"wrote {LAYOUT_PATH}")


main()
