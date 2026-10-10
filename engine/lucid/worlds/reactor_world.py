"""LingBot World 2 on Reactor as a robot environment.

The session is a live WebRTC stream that bills every second it is `ready`, so this class:
  * authorises the planned length against the local ledger before connecting,
  * mints its token with max_session_duration_seconds so Reactor enforces the cap server-side,
  * stops itself a couple of seconds before the grant runs out,
  * records actual ready-to-disconnect seconds in the ledger on close, whatever happened.

Frames arrive at up to 48 fps; each chunk_complete message marks a chunk boundary and names
the action that was active for that chunk, which is the label we trust (not what we sent).
"""
import asyncio
import threading
import time
from collections import deque
from pathlib import Path

import cv2

from .. import budget
from ..actions import CONTROLS, EMBODIMENTS, Controls, from_server_action
from ..config import ASSETS, env
from ..prompts import MOVING, WORLDS, compose
from .base import Chunk, Scene, World

MODEL = "reactor/lingbot-world-2"
# Measured by scripts/probe.py: an action sent after observing chunk k is first active in
# chunk k+2. Used to label camera-pose moves, which the server's active_action omits.
LATENCY_CHUNKS = 2
# Also measured: ~1.94 chunks/s, and reset + upload + image decode takes ~9 s per episode.
CHUNKS_PER_SECOND = 1.9
START_OVERHEAD_S = 10.0
KEEP_SIZE = (416, 240)  # frames are downsampled on arrival; 1664x960 is never kept in memory
DISPLAY_SIZE = (960, 554)  # what the dashboard shows when it is not attached to the stream itself
DISPLAY_FPS = 24
EVENT_CHUNKS = 8  # a live event stays in the prompt for ~4 s, like a held key
DEFAULT_SEED = ASSETS / "seeds" / "forest.jpg"


class ReactorWorld(World):
    kind = "reactor"

    def __init__(self, embodiment="drone", model=MODEL, rotation_speed_deg: float = 5.0, log=print):
        super().__init__(embodiment)
        self.model = model
        self.rotation_speed = rotation_speed_deg
        self.log = log
        self.reactor = None
        self.grant = None
        self.t_ready = None
        # Reactor's cap clock starts before connect() returns (a 60 s cap cut a session ~61 s
        # after our `ready` log, with a 3 s guard in place), so time left is counted from
        # before connect(): conservative by the few seconds connecting takes.
        self.t_created = None
        self.closed_seconds = 0.0
        self._frames = deque(maxlen=240)
        self._frames_lock = threading.Lock()
        self._chunks: asyncio.Queue | None = None
        self._image_ok: asyncio.Event | None = None
        self._loop = None
        self.controls = Controls()
        self.sent_action = "hover"
        self.sent_log = []  # (index of the chunk observed before sending, action)
        self.state = {}
        self.errors = deque(maxlen=20)
        self.frames_total = 0
        self.index = 0
        self.on_display = None  # callback(rgb frame), called from the SDK's frame thread
        self._last_display = 0.0
        self.last_hires = None
        self.layered = None  # lucid.prompts.World when the scene uses layered prompts
        self.moving = False
        self.held_events: list[tuple[str, int]] = []  # (event, chunk index it expires at)

    # ---- lifecycle -----------------------------------------------------------------------
    async def open(self, planned_seconds: float) -> None:
        from reactor_sdk import Reactor  # imported lazily so the mock never needs it

        key = env("REACTOR_API_KEY")
        if not key:
            raise RuntimeError("REACTOR_API_KEY is not set (put it in .env.local)")
        self.grant = budget.authorize(self.model, planned_seconds)
        self._loop = asyncio.get_running_loop()
        self._chunks = asyncio.Queue()
        self._image_ok = asyncio.Event()
        self.reactor = Reactor(model_name=self.model, api_key=key,
                               max_session_duration_seconds=self.grant.seconds)
        self.reactor.on_message(self._on_message)
        self.reactor.track("main_video").on_frame(self._on_frame)
        self.log(f"reactor: connecting to {self.model} (cap {self.grant.seconds}s, "
                 f"${self.grant.seconds * self.grant.rate:.2f} max)")
        self.t_created = time.monotonic()
        try:
            await self.reactor.connect()
        except Exception:
            await self._safe_disconnect()
            raise
        self.t_ready = time.monotonic()
        self.log(f"reactor: ready, session {self.reactor.session_id} — billing started")
        await self.reactor.send_command("set_rotation_speed_deg", {"rotation_speed_deg": self.rotation_speed})

    async def close(self) -> None:
        await self._safe_disconnect()

    async def _safe_disconnect(self):
        if self.reactor is None:
            return
        try:
            await self.reactor.disconnect()
        except Exception as e:  # noqa: BLE001 - always record what was billed
            self.log(f"reactor: disconnect error {e!r}")
        finally:
            if self.t_ready is not None:
                self.closed_seconds = time.monotonic() - self.t_ready
                entry = budget.record(self.model, self.closed_seconds, "lucid-session", self.grant.rate)
                self.log(f"reactor: session closed after {entry['seconds']}s, ${entry['usd']:.3f}")
            self.reactor, self.t_ready = None, None

    def time_left(self) -> float | None:
        if self.grant is None or self.t_created is None:
            return None
        return self.grant.seconds - (time.monotonic() - self.t_created)

    def episode_seconds(self, max_chunks: int) -> float:
        return max_chunks / CHUNKS_PER_SECOND + START_OVERHEAD_S

    def elapsed(self) -> float:
        return time.monotonic() - self.t_ready if self.t_ready else self.closed_seconds

    def usage(self) -> dict:
        s = self.elapsed()
        rate = self.grant.rate if self.grant else budget.rate_per_second(self.model)
        return {"backend": "reactor", "model": self.model, "seconds": round(s, 1),
                "usd": round(s * rate, 3), "cap_seconds": self.grant.seconds if self.grant else None,
                "frames": self.frames_total, "chunks": self.index}

    # ---- callbacks (may run off the event loop thread) -------------------------------------
    def _on_frame(self, frame):
        now = time.monotonic()
        small = cv2.resize(frame, KEEP_SIZE, interpolation=cv2.INTER_AREA)
        with self._frames_lock:
            self._frames.append((now, small))
            self.frames_total += 1
        if now - self._last_display >= 1.0 / DISPLAY_FPS:
            self._last_display = now
            self.last_hires = cv2.resize(frame, DISPLAY_SIZE, interpolation=cv2.INTER_AREA)
            if self.on_display:
                self.on_display(self.last_hires)

    def _on_message(self, msg):
        if not isinstance(msg, dict):
            return
        kind, data = msg.get("type"), msg.get("data") or {}
        if kind == "chunk_complete":
            self._loop.call_soon_threadsafe(self._chunks.put_nowait, (time.monotonic(), data))
        elif kind == "image_accepted":
            self._loop.call_soon_threadsafe(self._image_ok.set)
        elif kind == "state":
            self.state = data
        elif kind == "command_error":
            self.errors.append(data)
            self.log(f"reactor: command_error {data}")

    # ---- environment API -----------------------------------------------------------------
    async def start(self, scene: Scene):
        r = self.reactor
        if self.state.get("started") or self.state.get("has_image"):
            await r.send_command("reset", {})
        self.layered = WORLDS[scene.world_key] if scene.world_key else None
        self.moving, self.held_events = False, []
        if self.layered:
            image = ASSETS / "seeds" / self.layered.image
        else:
            image = Path(scene.seed_image) if scene.seed_image else DEFAULT_SEED
        self._image_ok.clear()
        ref = await r.upload_file(str(image))
        await r.send_command("set_image", {"image": ref})
        await asyncio.wait_for(self._image_ok.wait(), timeout=30)
        await r.send_command("set_seed", {"seed": int(scene.seed) % 2_147_483_647})
        await r.send_command("set_prompt", {"prompt": self.current_prompt() if self.layered else scene.prompt})
        self.controls = Controls()
        await self._apply(CONTROLS["hover"], force=True)
        self.sent_action = "hover"
        self.sent_log = []
        self.index = 0
        while not self._chunks.empty():
            self._chunks.get_nowait()
        with self._frames_lock:
            self._frames.clear()
        await r.send_command("start", {})
        self.log(f"reactor: started '{scene.name}' with {image.name}")
        return None

    async def reanchor(self, rgb, seed: int = 0) -> None:
        """Restart generation from a frame the world audit trusted (lucid.audit): the model forgets
        the drifted context and continues from the last place that still matched the seed. Same
        session, so it costs only the restart time (~9 s), not a new connection."""
        r = self.reactor
        path = ASSETS.parent / "data" / "tmp" / f"anchor-{int(time.time())}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
        await r.send_command("reset", {})
        self._image_ok.clear()
        ref = await r.upload_file(str(path))
        await r.send_command("set_image", {"image": ref})
        await asyncio.wait_for(self._image_ok.wait(), timeout=30)
        await r.send_command("set_seed", {"seed": int(seed) % 2_147_483_647})
        if self.layered:
            await r.send_command("set_prompt", {"prompt": self.current_prompt()})
        # Keep flying what was flying: the command is active from the first new chunk.
        await self._apply(CONTROLS[self.sent_action], force=True)
        self.sent_log = [(self.index - LATENCY_CHUNKS, self.sent_action)]
        while not self._chunks.empty():
            self._chunks.get_nowait()
        with self._frames_lock:
            self._frames.clear()
        await r.send_command("start", {})
        self.log(f"reactor: re-anchored at chunk {self.index} from a trusted frame")

    async def act(self, action: str) -> None:
        if action not in EMBODIMENTS[self.embodiment]:
            raise ValueError(f"{action} is not available to a {self.embodiment}")
        await self._apply(CONTROLS[action])
        if action != self.sent_action:
            self.sent_log.append((self.index - 1, action))
        self.sent_action = action
        if self.layered and (action in MOVING) != self.moving:
            self.moving = action in MOVING
            await self._send_prompt()

    def current_prompt(self) -> str:
        return compose(self.layered, self.moving, [e for e, _ in self.held_events])

    async def _send_prompt(self):
        await self.reactor.send_command("set_prompt", {"prompt": self.current_prompt()})

    def _expected_active(self, index: int) -> str:
        active = "hover"
        for sent_at, action in self.sent_log:
            if sent_at <= index - LATENCY_CHUNKS:
                active = action
        return active

    async def _apply(self, target: Controls, force=False):
        """Send only the axes that changed: commands are persistent state, not pulses."""
        r, cur, sends = self.reactor, self.controls, []
        if force or target.move_longitudinal != cur.move_longitudinal:
            sends.append(r.send_command("set_move_longitudinal", {"move_longitudinal": target.move_longitudinal}))
        if force or target.move_lateral != cur.move_lateral:
            sends.append(r.send_command("set_move_lateral", {"move_lateral": target.move_lateral}))
        if force or target.look_horizontal != cur.look_horizontal:
            sends.append(r.send_command("set_look_horizontal", {"look_horizontal": target.look_horizontal}))
        if force or target.camera_pose != cur.camera_pose:
            sends.append(r.send_command("set_camera_pose", {"camera_pose": list(target.camera_pose)}))
        if sends:
            await asyncio.gather(*sends)
        self.controls = target

    async def set_rotation_speed(self, deg_per_latent_frame: float) -> None:
        self.rotation_speed = deg_per_latent_frame
        if self.reactor is not None:
            await self.reactor.send_command("set_rotation_speed_deg", {"rotation_speed_deg": deg_per_latent_frame})

    async def steer(self, prompt: str) -> None:
        """Layered worlds take an event (label or clause) held for a few seconds; others a full prompt."""
        if self.layered:
            self.held_events.append((prompt, self.index + EVENT_CHUNKS))
            await self._send_prompt()
        else:
            await self.reactor.send_command("set_prompt", {"prompt": prompt})

    async def next_chunk(self, timeout: float = 20.0) -> Chunk:
        left = self.time_left()
        if left is not None and left < 3:
            raise budget.BudgetExceeded("session cap nearly reached; stopping before Reactor cuts us off")
        t_msg, data = await asyncio.wait_for(self._chunks.get(), timeout=timeout)
        await asyncio.sleep(0.03)  # let the boundary's last frames land
        with self._frames_lock:
            frames = [f for t, f in self._frames]
            self._frames.clear()
        if not frames:
            for _ in range(20):
                await asyncio.sleep(0.05)
                with self._frames_lock:
                    if self._frames:
                        frames = [f for t, f in self._frames]
                        self._frames.clear()
                        break
        if not frames:
            raise RuntimeError("chunk completed but no video frames arrived")
        raw = data.get("active_action")
        action = from_server_action(raw, self._expected_active(self.index))
        keep = frames if len(frames) <= 3 else [frames[0], frames[len(frames) // 2], frames[-1]]
        chunk = Chunk(index=self.index, frames=keep, action=action, raw_action=raw,
                      info={"server_chunk": data.get("chunk_index"), "frames_received": len(frames),
                            "elapsed_s": round(self.elapsed(), 2)},
                      hires=self.last_hires)
        self.index += 1
        if self.layered and any(until <= self.index for _, until in self.held_events):
            self.held_events = [(e, until) for e, until in self.held_events if until > self.index]
            await self._send_prompt()  # the event's key was "released"
        return chunk
