from dataclasses import dataclass, field

import numpy as np


@dataclass
class Scene:
    name: str
    prompt: str
    seed_image: str | None = None  # required by LingBot World 2, ignored by the mock
    seed: int = 42
    params: dict = field(default_factory=dict)  # mock-world knobs (density, fog, palette)
    # Mid-episode perturbations: [{"at": chunk_index, "prompt": "..."}]. On the world model
    # the prompt is hot-swapped; on the mock it is parsed for keywords (fog, night, obstacle).
    events: list = field(default_factory=list)
    # Third-person drone worlds (lucid.prompts.WORLDS): the prompt is recomposed from layers
    # as movement starts and stops, instead of being one fixed string.
    world_key: str | None = None


@dataclass
class Chunk:
    index: int
    frames: list  # RGB uint8 arrays, oldest first
    action: str  # the action that actually generated this chunk (after control latency)
    raw_action: str | None = None  # what the backend reported, verbatim
    info: dict = field(default_factory=dict)  # ground truth, when the backend has any
    hires: np.ndarray | None = None  # display-resolution frame for detectors and the dashboard


class World:
    """One controllable world. Async because the real backend is a live WebRTC session."""

    kind = "base"
    has_ground_truth = False

    def __init__(self, embodiment: str = "drone"):
        self.embodiment = embodiment

    async def open(self, planned_seconds: float) -> None: ...

    async def start(self, scene: Scene) -> np.ndarray | None: ...

    async def act(self, action: str) -> None: ...

    async def steer(self, prompt: str) -> None: ...

    async def next_chunk(self) -> Chunk: ...

    async def close(self) -> None: ...

    def usage(self) -> dict:
        return {}

    def time_left(self) -> float | None:
        """Seconds before the backend ends the session, or None if unlimited."""
        return None

    def episode_seconds(self, max_chunks: int) -> float:
        return 0.0
