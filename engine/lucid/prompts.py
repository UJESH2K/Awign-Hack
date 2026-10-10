"""Layered prompts for a third-person drone, following LingBot World 2's prompt guide.

    prompt = base + camera[moving] + movement[moving] + events

The base casts the world once; the camera and movement layers swap between static and
dynamic variants whenever movement input starts or stops, so the text always matches the
motion the model is asked to render. The camera templates are the guide's production
sentences, kept verbatim with the subject substituted: paraphrasing them breaks control.
"""
from dataclasses import dataclass, field

SUBJECT = "the drone"

CAMERA_STATIC = (
    f"Third-person view, {SUBJECT} locked at the exact centre of the frame at constant size and distance. "
    f"Neither {SUBJECT} nor the camera moves on its own; arrow-key look-input is the only source of camera "
    f"motion, arcing the camera around the stationary, centred {SUBJECT} only while held."
)
CAMERA_DYNAMIC = (
    f"Strict third-person rear view, {SUBJECT} locked at the exact centre of the frame as the camera holds a "
    f"fixed position behind it and tracks it forward. The camera does not rotate around {SUBJECT}; "
    f"look-input becomes {SUBJECT} changing heading."
)
MOVE_STATIC = (
    "The drone hovers in place, its four rotors a steady blur, its body bobbing a few centimetres "
    "as dust drifts in the air beneath it."
)
MOVE_DYNAMIC = (
    "The drone flies steadily forward at waist height, rotors a blur and body tilted slightly nose-down, "
    "moving directly away from the camera so it stays in strict rear view, the ground sliding past below it."
)

# Moving = WASD held. Look-only input (yaw) keeps the static variant, as in the reference app.
MOVING = {"forward", "back", "left", "right", "arc_left", "arc_right", "up", "down"}


@dataclass
class World:
    key: str
    title: str
    image: str  # file in engine/assets/seeds
    base: str
    events: dict = field(default_factory=dict)  # label -> clause (contextual-entrance form)
    mock: dict = field(default_factory=dict)  # mock-world knobs for the same scene
    # Where the drone sits in the seed image (normalised x, y, w, h), and a padded version
    # of it that perception ignores, since the drone is pinned there in every frame.
    drone_box: tuple = (0.38, 0.459, 0.24, 0.2)
    flow_mask: tuple = (0.35, 0.42, 0.30, 0.28)


_KEEP = "The drone remains the main subject, unchanged in size and position, while "

WORLDS = {
    "forest": World(
        key="forest",
        title="Woodland path",
        image="forest_drone.jpg",
        base=("A small white quadcopter drone with red stripes, four spinning rotors and a black camera gimbal "
              "flies at waist height above a sunlit woodland path. The world contains EXACTLY ONE drone. "
              "Wooden posts and white signboards stand beside the path, tall oak trunks and green ferns "
              "line both sides, dappled summer light, photorealistic."),
        events={
            "worker steps in": _KEEP + "a park ranger in a green jacket steps onto the path a few metres ahead.",
            "branch falls": _KEEP + "a heavy branch drops from an oak and lands across the path ahead.",
            "fog rolls in": _KEEP + "thick white fog rolls between the trees and visibility drops to a few metres.",
            "dusk": _KEEP + "the light fades to a deep blue dusk and the drone's two front lights glow.",
        },
        mock={"palette": "forest", "density": 6.0},
    ),
    "warehouse": World(
        key="warehouse",
        title="Warehouse floor",
        image="warehouse_drone.jpg",
        base=("A small white quadcopter drone with red stripes, four spinning rotors and a black camera gimbal "
              "flies above the concrete floor of a large warehouse. The world contains EXACTLY ONE drone. "
              "Rows of white plastic tanks in metal cages and stacks of blue drums form long aisles, "
              "steel columns hold a high roof, bright even industrial light, photorealistic."),
        events={
            "worker steps in": _KEEP + "a warehouse worker in a yellow high-visibility vest walks into the aisle ahead.",
            "forklift crosses": _KEEP + "an orange forklift carrying a pallet crosses the aisle ahead.",
            "pallet falls": _KEEP + "a pallet of boxes topples from a stack into the aisle ahead.",
            "lights fail": _KEEP + "the overhead lights flicker and the warehouse drops into dim emergency lighting.",
        },
        mock={"palette": "warehouse", "density": 7.0},
        drone_box=(0.38, 0.42, 0.24, 0.2),
        flow_mask=(0.35, 0.38, 0.30, 0.28),
    ),
}


def compose(world: World, moving: bool, events: list[str] | None = None) -> str:
    parts = [world.base, CAMERA_DYNAMIC if moving else CAMERA_STATIC, MOVE_DYNAMIC if moving else MOVE_STATIC]
    parts += [world.events[e] if e in world.events else e for e in (events or [])]
    prompt = " ".join(parts)
    # The encoder truncates around 2000 characters; drop the oldest events first, never the contracts.
    while len(prompt) > 1900 and events:
        events = events[1:]
        return compose(world, moving, events)
    return prompt
