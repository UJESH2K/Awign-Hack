"""World-model audit: every way a generated world goes wrong, caught frame by frame.

A world model is asked to keep one place, one drone, and only the obstacles the operator asked
for. On long flights LingBot World 2 measurably breaks all three (see data/bank). Signals:

  scene drift    the place turns into another place        ResNet-18 (ImageNet) embedding of the
                                                            frame, drone masked out, vs the seed photo
  scene cut      a jump between consecutive chunks          the same embedding vs the previous chunk
  colour shift   lighting / white balance wanders           mean CIELAB colour vs the seed (delta E)
  drone morphed  the drone grows, shrinks, stretches or     embedding of crops around the drone at
                 stops looking like itself                  several sizes vs the seed's drone crop
  pop-in         an obstacle appears out of nowhere, not    a detection with no track in the two
                 at the frame edge, without a request       chunks before, that persists into the next

Every event keeps the chunk, the measured value, a box where there is one, and a thumbnail, so
each instance where the model messed up can be shown. The audit also says when the world should
be re-anchored (restarted from the last frame it trusted).
"""
import base64
import threading
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .config import ASSETS

# Thresholds calibrated on the recorded LingBot flights in data/bank (scripts/audit_bank.py).
# Kept places (forest, 143 chunks) stay at 0.86-0.92 to the seed; places that turned into another
# room fall to 0.67-0.79. Healthy drones match their seed crop at 0.80-0.95; ballooned or
# re-rendered ones at 0.71-0.76. Consecutive chunks of real motion stay above 0.85.
SCENE_MIN = 0.80  # cosine to the seed below which the place no longer reads as the seed's place
CUT_MIN = 0.70  # cosine between consecutive chunks below which it is a cut, not motion
COLOUR_MAX = 20.0  # delta E (CIELAB) of the mean background colour vs the seed (kept places: up to 14)
DRONE_SCALES = (0.8, 1.0, 1.3, 1.7, 2.2)
DRONE_MIN = 0.78  # best crop similarity to the seed's drone
POP_CONF = 0.5
POP_MIN_H = 0.3  # of frame height: near enough to matter. Seated people in a crowded venue (0.12-0.25) flicker in and out
STREAK = 2  # chunks a condition must hold before it is an event (one bad frame is noise)

_embedder = None
_lock = threading.Lock()


def _load_embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            import torch
            import torchvision

            m = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.IMAGENET1K_V1)
            m.fc = torch.nn.Identity()
            m.eval()
            _embedder = m
    return _embedder


def embed(rgbs: list[np.ndarray], hide: tuple | None = None) -> np.ndarray:
    """L2-normalised 512-d ResNet-18 features; `hide` (normalised x, y, w, h) is filled with the
    frame's mean colour first so the drone does not dominate the scene's identity."""
    import torch

    batch = []
    for rgb in rgbs:
        im = cv2.resize(rgb, (384, 224), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        if hide:
            x, y, w, h = hide
            im[int(y * 224):int((y + h) * 224), int(x * 384):int((x + w) * 384)] = im.reshape(-1, 3).mean(0)
        im = (im - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
        batch.append(im.transpose(2, 0, 1))
    with torch.no_grad():
        z = _load_embedder()(torch.from_numpy(np.stack(batch)).float()).numpy()
    return z / (np.linalg.norm(z, axis=1, keepdims=True) + 1e-8)


def _lab_mean(rgb: np.ndarray, hide: tuple | None) -> np.ndarray:
    small = cv2.resize(rgb, (192, 108), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab[..., 0] *= 100.0 / 255.0
    lab[..., 1:] -= 128.0
    keep = np.ones(lab.shape[:2], bool)
    if hide:
        x, y, w, h = hide
        keep[int(y * 108):int((y + h) * 108), int(x * 192):int((x + w) * 192)] = False
    return lab[keep].mean(0)


def _b64(rgb: np.ndarray, box=None, width=320) -> str:
    h = int(width * rgb.shape[0] / rgb.shape[1])
    im = cv2.cvtColor(cv2.resize(rgb, (width, h), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR)
    if box is not None:
        x0, y0, x1, y1 = box
        cv2.rectangle(im, (int(x0 * width), int(y0 * h)), (int(x1 * width), int(y1 * h)), (61, 37, 194), 2)
    return base64.b64encode(cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 72])[1].tobytes()).decode()


@dataclass
class Event:
    chunk: int
    kind: str  # scene drift | scene cut | colour shift | drone morphed | pop-in
    value: float
    detail: str
    box: list | None = None
    thumb: str | None = None


@dataclass
class Reading:
    chunk: int
    scene: float  # cosine to the seed, drone hidden
    continuity: float | None  # cosine to the previous chunk
    colour: float  # delta E of mean background colour vs the seed
    drone_scale: float  # scale the seed's drone is found at (1 = as seeded)
    drone_match: float
    trusted: bool
    events: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("scene", "continuity", "colour", "drone_scale", "drone_match"):
            if d[k] is not None:
                d[k] = round(float(d[k]), 3)
        d["events"] = [{k: v for k, v in e.items() if k != "thumb"} for e in d["events"]]
        return d


class WorldAudit:
    """Feed it one frame per chunk; it returns a Reading and keeps the log of events."""

    def __init__(self, spec, detector=None, thumbs: bool = True):
        self.spec = spec
        x, y, w, h = spec.drone_box
        self.drone = (x, y, w, h)
        self.hide = (max(0.0, x - 0.04), max(0.0, y - 0.06), w + 0.08, h + 0.12)
        seed = cv2.cvtColor(cv2.imread(str(ASSETS / "seeds" / spec.image)), cv2.COLOR_BGR2RGB)
        self.seed = seed
        self.seed_z = embed([seed], self.hide)[0]
        self.seed_lab = _lab_mean(seed, self.hide)
        self.detector = detector
        self.thumbs = thumbs
        self.reset()

    def reset(self):
        self.prev_z = None
        self.hist = []  # detections of the last chunks, newest last
        self.pending = []  # pop-in candidates from the previous chunk, confirmed if they persist
        self.streak = {}
        self.log: list[Event] = []
        self.readings: list[Reading] = []
        self.last_trusted = None  # (chunk, rgb) of the latest frame that passed every check
        self.requested_until = -1  # chunk until which a requested event may legitimately add objects
        self.anchors: list[dict] = []  # re-anchors: {chunk, from_chunk}

    def expect_change(self, chunk: int, horizon: int = 6):
        """The operator asked for an event: objects appearing in the next chunks are not a fault."""
        self.requested_until = chunk + horizon

    # ---- signals ------------------------------------------------------------------------
    def _drone_crops(self, rgb: np.ndarray, scales) -> tuple[list, list]:
        """Crops centred on the drone's place, `scale` x its seeded size (with some context)."""
        H, W = rgb.shape[:2]
        x, y, w, h = self.drone
        cx, cy = (x + w / 2) * W, (y + h / 2) * H
        crops, boxes = [], []
        for s in scales:
            cw, ch = w * W * s * 1.3, h * H * s * 1.95
            x0, y0, x1, y1 = int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2)
            pad = max(0, -x0, -y0, x1 - W, y1 - H)
            img = cv2.copyMakeBorder(rgb, pad, pad, pad, pad, cv2.BORDER_CONSTANT) if pad else rgb
            crops.append(cv2.resize(img[y0 + pad:y1 + pad, x0 + pad:x1 + pad], (160, 160), interpolation=cv2.INTER_AREA))
            boxes.append((max(0.0, x0 / W), max(0.0, y0 / H), min(1.0, x1 / W), min(1.0, y1 / H)))
        return crops, boxes

    def drone_fit(self, rgb: np.ndarray) -> tuple[float, float, tuple]:
        """How much the drone still looks like the seed's drone, at the best of several sizes: (scale, similarity, box)."""
        if not hasattr(self, "_drone_ref"):
            self._drone_ref = embed(self._drone_crops(self.seed, [1.0])[0])[0]
        crops, boxes = self._drone_crops(rgb, DRONE_SCALES)
        sims = embed(crops) @ self._drone_ref
        i = int(np.argmax(sims))
        return DRONE_SCALES[i], float(sims[i]), boxes[i]

    def detections(self, rgb: np.ndarray) -> list[tuple]:
        """(COCO label, confidence, normalised x0 y0 x1 y1) from the shared YOLO detector."""
        if self.detector is None:
            return []
        r = self.detector.predict(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), imgsz=640, conf=POP_CONF, verbose=False)[0]
        H, W = rgb.shape[:2]
        return [(r.names[int(k)], float(c), (b[0] / W, b[1] / H, b[2] / W, b[3] / H))
                for b, c, k in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist())]

    def _candidates(self, raw: list[tuple]) -> list[tuple]:
        from .sentinel import HAZARDS, category

        x, y, w, h = self.hide
        out = []
        for label, c, box in raw:
            if c < POP_CONF:
                continue
            on_drone = box[0] < x + w and box[2] > x and box[1] < y + h and box[3] > y
            kind = category(label)
            # People and vehicles big enough not to flicker in a crowd; other obstacles only when
            # large. Never the drone itself, which the detector reads as a kite, airplane or bench.
            big = box[3] - box[1] >= (POP_MIN_H if kind != "obstacle" else 1.5 * POP_MIN_H)
            if label in HAZARDS and big and not (on_drone and kind != "person"):
                out.append((kind, float(c), box))
        return out

    # ---- per chunk ----------------------------------------------------------------------
    def update(self, rgb: np.ndarray, chunk: int, detections: list[tuple] | None = None) -> Reading:
        """One chunk's last frame. `detections` (COCO label, conf, box) saves a second detector pass
        when the Sentinel has already run on this frame."""
        z = embed([rgb], self.hide)[0]
        scene = float(z @ self.seed_z)
        cont = float(z @ self.prev_z) if self.prev_z is not None else None
        colour = float(np.linalg.norm(_lab_mean(rgb, self.hide) - self.seed_lab))
        scale, match, dbox = self.drone_fit(rgb)
        dets = self._candidates(detections if detections is not None else self.detections(rgb))
        found = []

        def held(name, cond):
            self.streak[name] = self.streak.get(name, 0) + 1 if cond else 0
            return self.streak[name] == STREAK  # report once, when it becomes persistent

        if held("scene drift", scene < SCENE_MIN):
            found.append(Event(chunk, "scene drift", scene, f"looks {scene:.0%} like the seed place"))
        if cont is not None and cont < CUT_MIN:
            found.append(Event(chunk, "scene cut", cont, f"only {cont:.0%} like the previous chunk: the place jumped"))
        if held("colour shift", colour > COLOUR_MAX):
            found.append(Event(chunk, "colour shift", colour, f"colour moved {colour:.0f} delta-E from the seed"))
        bad_drone = match < DRONE_MIN
        if held("drone morphed", bad_drone):
            found.append(Event(chunk, "drone morphed", match, f"the drone looks {match:.0%} like itself", list(dbox)))
        # Pop-in: last chunk's new, mid-frame object is confirmed if it is still there now.
        for label, conf, box, rgb_then in self.pending:
            if any(_near(box, b) for _, _, b in dets):
                e = Event(chunk - 1, "pop-in", conf, f"a {label} appeared mid-frame without being asked for", list(box))
                e.thumb = _b64(rgb_then, box) if self.thumbs else None
                found.append(e)
                break
        self.pending = []
        if len(self.hist) >= 3 and chunk > self.requested_until:
            for label, conf, box in dets:
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                edge = box[0] < 0.04 or box[2] > 0.96 or box[1] < 0.04 or box[3] > 0.96
                seen = any(_near(box, b) for past in self.hist[-3:] for _, _, b in past)
                if not edge and not seen and 0.15 < cx < 0.85 and cy > 0.2:
                    self.pending.append((label, conf, box, rgb))
        self.hist = (self.hist + [dets])[-3:]
        if self.thumbs:
            for e in found:
                if e.thumb is None:
                    e.thumb = _b64(rgb, e.box)
        trusted = scene >= SCENE_MIN and colour <= COLOUR_MAX and not bad_drone and (cont is None or cont >= CUT_MIN)
        if trusted:
            self.last_trusted = (chunk, rgb)
        self.prev_z = z
        self.log.extend(found)
        reading = Reading(chunk, scene, cont, colour, scale, match, trusted, found)
        self.readings.append(reading)
        return reading

    def should_reanchor(self, patience: int = 4, cooldown: int = 16) -> bool:
        """Re-anchor once the world has failed checks for `patience` chunks in a row (and not again
        until it has had `cooldown` chunks to settle)."""
        recent = self.readings[-patience:]
        last = self.anchors[-1]["chunk"] if self.anchors else -cooldown
        return (len(recent) == patience and not any(r.trusted for r in recent) and self.last_trusted is not None
                and recent[-1].chunk - last >= cooldown)

    def reanchored(self, chunk: int) -> dict:
        """The world was restarted from the last trusted frame: a deliberate cut, not a fault."""
        source = self.last_trusted[0]
        self.anchors.append({"chunk": chunk, "from_chunk": source})
        self.prev_z, self.hist, self.pending, self.streak = None, [], [], {}
        return self.anchors[-1]

    def snapshot(self, events: int = 24) -> dict:
        """What the dashboard shows: the latest reading, the running summary and recent events."""
        last = self.readings[-1].to_dict() if self.readings else None
        return {**self.summary(), "latest": last, "anchors": list(self.anchors),
                "series": [{"k": r.chunk, "scene": round(r.scene, 3), "drone": round(r.drone_match, 3),
                            "colour": round(r.colour, 1), "ok": r.trusted} for r in self.readings[-120:]],
                "events": [{**e.__dict__, "value": round(float(e.value), 3)} for e in self.log[-events:]]}

    def summary(self) -> dict:
        n = len(self.readings) or 1
        kinds = {}
        for e in self.log:
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        return {"chunks": len(self.readings), "trusted_share": round(sum(r.trusted for r in self.readings) / n, 3),
                "counts": kinds, "first_failure": next((e.chunk for e in self.log), None), "reanchors": len(self.anchors),
                "thresholds": {"scene_min": SCENE_MIN, "cut_min": CUT_MIN, "colour_max": COLOUR_MAX, "drone_min": DRONE_MIN}}


def _near(a, b, tol=0.12) -> bool:
    """Same object one chunk later: overlapping, or its centre moved less than `tol` of the frame."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    if ix * iy > 0:
        return True
    return np.hypot((a[0] + a[2] - b[0] - b[2]) / 2, (a[1] + a[3] - b[1] - b[3]) / 2) < tol
