"""A clip under review: one first-person video and its action annotations.

On disk (data/solosim/clips/<id>/):
    video.mp4          the footage the reviewer plays (browser-friendly H.264)
    annotations.json   {"segments": [{id, start, end, verb, noun, narration}], "source": ...}
    signals.npz        per-sample measurements (signals.py), cached
    report.json        checks + issues (checks.py)
    review.json        the tester's decisions per segment
"""
import csv
import threading
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2

ENGINE = Path(__file__).resolve().parents[1]
DATA = ENGINE / "data"
CLIPS = DATA / "solosim" / "clips"


@dataclass
class Segment:
    id: str
    start: float  # seconds
    end: float
    verb: str
    noun: str
    narration: str
    meta: dict = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2

    @property
    def length(self) -> float:
        return self.end - self.start


class Clip:
    def __init__(self, clip_id: str):
        self.id = clip_id
        self.dir = CLIPS / clip_id
        if not (self.dir / "annotations.json").exists():
            raise FileNotFoundError(clip_id)
        ann = json.loads((self.dir / "annotations.json").read_text(encoding="utf-8"))
        self.source = ann.get("source", {})
        self.title = ann.get("title", clip_id)
        self.task = ann.get("task", "")
        self.segments = [Segment(**s) for s in ann["segments"]]
        cap = cv2.VideoCapture(str(self.video))
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width, self.height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        self.duration = self.frames / self.fps
        self._cap = None
        self._lock = threading.Lock()  # one decoder, many threads asking for frames

    @property
    def video(self) -> Path:
        return self.dir / "video.mp4"

    def frame_at(self, t: float):
        """RGB frame at time t (seconds)."""
        with self._lock:
            if self._cap is None:
                self._cap = cv2.VideoCapture(str(self.video))
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(self.frames - 1, int(round(t * self.fps)))))
            ok, im = self._cap.read()
        return cv2.cvtColor(im, cv2.COLOR_BGR2RGB) if ok else None

    def segments_json(self) -> list[dict]:
        return [asdict(s) for s in self.segments]

    def save_segments(self, segments: list[Segment]):
        ann = json.loads((self.dir / "annotations.json").read_text(encoding="utf-8"))
        ann["segments"] = [asdict(s) for s in segments]
        (self.dir / "annotations.json").write_text(json.dumps(ann, indent=1), encoding="utf-8")
        self.segments = segments

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "task": self.task, "duration": round(self.duration, 2),
                "fps": round(self.fps, 2), "width": self.width, "height": self.height,
                "segments": len(self.segments), "source": self.source}


def list_clips() -> list[str]:
    return sorted(p.name for p in CLIPS.glob("*") if (p / "annotations.json").exists()) if CLIPS.exists() else []


def _ts(s: str) -> float:
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def import_epic(video_id: str, video_path: Path, csv_paths: list[Path], clip_id: str | None = None,
                title: str | None = None) -> Clip:
    """EPIC-KITCHENS-100 video + its narrated action segments -> a clip."""
    rows = []
    for p in csv_paths:
        rows += [r for r in csv.DictReader(open(p, encoding="utf-8")) if r["video_id"] == video_id]
    rows.sort(key=lambda r: _ts(r["start_timestamp"]))
    clip_id = clip_id or video_id
    d = CLIPS / clip_id
    d.mkdir(parents=True, exist_ok=True)
    if Path(video_path).resolve() != (d / "video.mp4").resolve():
        shutil.copyfile(video_path, d / "video.mp4")
    segs = [{"id": r["narration_id"], "start": round(_ts(r["start_timestamp"]), 2), "end": round(_ts(r["stop_timestamp"]), 2),
             "verb": r["verb"], "noun": r["noun"].split(":")[0] if ":" not in r["noun"] else " ".join(reversed(r["noun"].split(":"))),
             "narration": r["narration"], "meta": {"verb_class": int(r["verb_class"]), "noun_class": int(r["noun_class"])}}
            for r in rows]
    ann = {"title": title or f"EPIC-KITCHENS {video_id}", "task": "kitchen activities, first-person (head-mounted GoPro)",
           "source": {"dataset": "EPIC-KITCHENS-100", "video_id": video_id, "licence": "CC BY-NC 4.0",
                      "annotation": "official narrated action segments (start/stop, verb, noun)"},
           "segments": segs}
    (d / "annotations.json").write_text(json.dumps(ann, indent=1), encoding="utf-8")
    return Clip(clip_id)
