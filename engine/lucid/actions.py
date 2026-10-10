"""Discrete action space shared by every world backend.

The robot *is* the camera: LingBot World 2 is a navigable world model whose controls are
camera motion, which is exactly a drone's or a rover's first-person view.
"""
from dataclasses import dataclass

# LingBot World 2 camera pose is y-down: negative ty moves the camera up.
_UP_POSE = [0.0, 0.0, 0.0, 0.0, -1.0, 0.0]
_DOWN_POSE = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]


@dataclass(frozen=True)
class Controls:
    move_longitudinal: str = "idle"
    move_lateral: str = "idle"
    look_horizontal: str = "idle"
    camera_pose: tuple = ()


CONTROLS = {
    "hover": Controls(),
    "forward": Controls(move_longitudinal="forward"),
    "back": Controls(move_longitudinal="back"),
    "left": Controls(move_lateral="strafe_left"),
    "right": Controls(move_lateral="strafe_right"),
    "yaw_left": Controls(look_horizontal="left"),
    "yaw_right": Controls(look_horizontal="right"),
    # Arcs keep translating while turning, so optical flow still carries depth.
    "arc_left": Controls(move_longitudinal="forward", look_horizontal="left"),
    "arc_right": Controls(move_longitudinal="forward", look_horizontal="right"),
    "up": Controls(camera_pose=tuple(_UP_POSE)),
    "down": Controls(camera_pose=tuple(_DOWN_POSE)),
}

# Expected optical-flow signature of each action as (du/dx, dv/dy, mean_u, mean_v).
# Image u points right and v points down. Moving forward stretches the image both ways;
# yawing or strafing left slides it right; climbing over a ground plane stretches it
# vertically only and slides it down.
SIGNATURES = {
    "hover": (0.0, 0.0, 0.0, 0.0),
    "forward": (1.0, 1.0, 0.0, 0.0),
    "back": (-1.0, -1.0, 0.0, 0.0),
    "left": (0.0, 0.0, 1.0, 0.0),
    "right": (0.0, 0.0, -1.0, 0.0),
    "yaw_left": (0.0, 0.0, 1.0, 0.0),
    "yaw_right": (0.0, 0.0, -1.0, 0.0),
    "arc_left": (0.5, 0.5, 1.0, 0.0),
    "arc_right": (0.5, 0.5, -1.0, 0.0),
    "up": (0.0, 1.0, 0.0, 1.0),
    "down": (0.0, -1.0, 0.0, -1.0),
}

EMBODIMENTS = {
    "drone": ["hover", "forward", "arc_left", "arc_right", "yaw_left", "yaw_right", "back",
              "left", "right", "up", "down"],
    "rover": ["hover", "forward", "arc_left", "arc_right", "yaw_left", "yaw_right", "back"],
}

# How LingBot World 2 reports the active movement/look in chunk_complete / state.
_SERVER_TOKENS = {
    "w": "forward",
    "s": "back",
    "a": "left",
    "d": "right",
    "left": "yaw_left",
    "right": "yaw_right",
}


def from_server_action(raw: str | None, fallback: str) -> str:
    """Map LingBot's '+'-joined active action (e.g. 'w', 'left', 'still') to our label.

    Camera-pose moves (up/down) are not reflected in that string, so the caller passes the
    action it knows it sent as `fallback`.
    """
    if not raw or raw == "still":
        return fallback if fallback in ("up", "down") else "hover"
    parts = [_SERVER_TOKENS.get(p) for p in raw.split("+")]
    parts = [p for p in parts if p]
    if not parts:
        return fallback
    if set(parts) == {"forward", "yaw_left"}:
        return "arc_left"
    if set(parts) == {"forward", "yaw_right"}:
        return "arc_right"
    return parts[0]
