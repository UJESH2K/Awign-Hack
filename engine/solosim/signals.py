"""Per-sample measurements of a first-person clip (default 5 samples/s), cached in signals.npz.

    blur          variance of the Laplacian (low = smeared by head motion or focus)
    bright        mean luma 0-255, plus the share of crushed-black and blown-white pixels
    head_motion   median optical flow: how fast the wearer's head (the camera) moves
    hand_motion   flow that is not the head moving: hands and objects acting
    hands         up to 2 boxes from a YOLOv8 hand detector (normalised x0 y0 x1 y1 conf)
    faces         up to 3 boxes from a YOLOv8 face detector: bystanders are a privacy issue
    emb           CLIP ViT-B/32 image embedding (512-d) to compare frames with label text
"""
import os
import time

import cv2
import numpy as np

from .clip_io import DATA, Clip

os.environ.setdefault("YOLO_OFFLINE", "true")
os.environ.setdefault("YOLO_AUTOINSTALL", "false")

RATE = 5.0
WEIGHTS = DATA / "weights"
_models = {}


def _yolo(name):
    if name not in _models:
        from ultralytics import YOLO

        _models[name] = YOLO(str(WEIGHTS / name))
    return _models[name]


def _clip():
    if "clip" not in _models:
        import clip
        import torch

        model, preprocess = clip.load("ViT-B/32", device="cpu")
        model.eval()
        _models["clip"] = (model, preprocess, torch, clip)
    return _models["clip"]


def embed_text(texts: list[str]) -> np.ndarray:
    model, _, torch, clip = _clip()
    with torch.no_grad():
        z = model.encode_text(clip.tokenize(texts, truncate=True)).float().numpy()
    return z / np.linalg.norm(z, axis=1, keepdims=True)


def _embed_images(rgbs: list[np.ndarray]) -> np.ndarray:
    from PIL import Image

    model, preprocess, torch, _ = _clip()
    with torch.no_grad():
        x = torch.stack([preprocess(Image.fromarray(im)) for im in rgbs])
        z = model.encode_image(x).float().numpy()
    return z / np.linalg.norm(z, axis=1, keepdims=True)


def _boxes(result, W, H, k):
    out = np.full((k, 5), np.nan, np.float32)
    b = sorted(zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist()), key=lambda x: -x[1])[:k]
    for i, (xyxy, c) in enumerate(b):
        out[i] = (xyxy[0] / W, xyxy[1] / H, xyxy[2] / W, xyxy[3] / H, c)
    return out


def compute(clip: Clip, rate: float = RATE, progress=None) -> dict:
    """Decode the video once, sampling `rate` frames per second."""
    hand, face = _yolo("hand_yolov8n.pt"), _yolo("face_yolov8n.pt")
    _clip()
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    cap = cv2.VideoCapture(str(clip.video))
    step = max(1, int(round(clip.fps / rate)))
    ts, blur, bright, dark, blown, head, act, hands, faces, frames = [], [], [], [], [], [], [], [], [], []
    prev = None
    i, t0 = 0, time.time()
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, bgr = cap.retrieve()
            if not ok:
                break
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            H, W = rgb.shape[:2]
            g = cv2.cvtColor(cv2.resize(bgr, (320, int(320 * H / W)), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            ts.append(i / clip.fps)
            blur.append(cv2.Laplacian(g, cv2.CV_64F).var())
            bright.append(g.mean())
            dark.append((g < 16).mean())
            blown.append((g > 245).mean())
            small = cv2.resize(g, (160, int(160 * H / W)), interpolation=cv2.INTER_AREA)
            if prev is not None:
                f = dis.calc(prev, small, None)
                med = np.median(f.reshape(-1, 2), axis=0)
                head.append(float(np.hypot(*med)) * rate / small.shape[1])  # frame-widths per second
                act.append(float(np.linalg.norm(f - med, axis=2).mean()) * rate / small.shape[1])
            else:
                head.append(0.0)
                act.append(0.0)
            prev = small
            hands.append(_boxes(hand.predict(bgr, imgsz=640, conf=0.2, verbose=False)[0], W, H, 2))
            faces.append(_boxes(face.predict(bgr, imgsz=640, conf=0.45, verbose=False)[0], W, H, 3))
            frames.append(cv2.resize(rgb, (224, int(224 * H / W)), interpolation=cv2.INTER_AREA))
            if progress and len(ts) % 25 == 0:
                progress(f"measured {ts[-1]:.0f} of {clip.duration:.0f} s", ts[-1] / clip.duration)
        i += 1
    cap.release()
    emb = np.concatenate([_embed_images(frames[j:j + 64]) for j in range(0, len(frames), 64)]) if frames else np.zeros((0, 512))
    sig = {"t": np.array(ts, np.float32), "blur": np.array(blur, np.float32), "bright": np.array(bright, np.float32),
           "dark": np.array(dark, np.float32), "blown": np.array(blown, np.float32), "head_motion": np.array(head, np.float32),
           "hand_motion": np.array(act, np.float32), "hands": np.array(hands, np.float32), "faces": np.array(faces, np.float32),
           "emb": emb.astype(np.float16), "rate": np.float32(rate), "seconds": np.float32(time.time() - t0)}
    np.savez_compressed(clip.dir / "signals.npz", **sig)
    return sig


def load(clip: Clip, progress=None) -> dict:
    f = clip.dir / "signals.npz"
    if f.exists():
        z = np.load(f)
        return {k: z[k] for k in z.files}
    return compute(clip, progress=progress)
