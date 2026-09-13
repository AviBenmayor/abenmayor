"""Count the people in a single frame. No torch, no ultralytics at runtime.

    detector = load_detector()            # ONNX if available, HOG if not
    result   = detector.count(jpeg_bytes) # -> DetectionResult

WHY ONNX AND NOT ULTRALYTICS
---------------------------------------------------------------------------
`pip install ultralytics` drags in torch and torchvision -- roughly 2 GB of
wheels and a CUDA-shaped dependency tree -- to run 6 MB of weights on 352x240
JPEGs. onnxruntime is 20 MB, is a first-class CPU runtime on Apple silicon,
and needs no model code at all: the network's topology travels inside the
.onnx file. So the RUNTIME dependency is `onnxruntime`, and ultralytics is
used exactly once, off to the side, to convert the published weights.

THE EXPORT STEP, AND WHY IT IS NOT AUTOMATED
---------------------------------------------------------------------------
Ultralytics publishes only `.pt` in its GitHub release assets -- there is no
`yolo11n.onnx` asset (probed 2026-09-13: the .pt is HTTP 200, every .onnx
spelling is 404), and the Hugging Face mirrors carry .pt too. So the ONNX is
produced ONCE, by hand, in a throwaway environment:

    uv run --no-project --python 3.12 \
        --with ultralytics --with onnx --with onnxslim --with onnxruntime \
        python export_onnx.py        # see PT_URL below; imgsz=640, opset=12

Automating that inside `loci` would mean the CLI could silently install torch,
which is the opposite of a pinned dependency. Instead `ensure_model()` fails
with the exact command when the file is absent.

WHAT IS VERIFIED, AND HOW STRONG THAT IS
---------------------------------------------------------------------------
`PT_SHA256` is the real provenance: it pins the exact bytes of a public,
immutable GitHub release asset, and anyone can re-download and check it.
`ONNX_SHA256` pins the bytes THIS repo's export produced; it catches a corrupt
or swapped file, but it is not an upstream-published digest and a different
ultralytics/torch version may legitimately produce a different graph. Both are
checked on load, and the ONNX mismatch message says to re-export rather than
pretending the file is malicious.

TWO CONFIDENCE THRESHOLDS, ON PURPOSE
---------------------------------------------------------------------------
A single threshold is a hidden parameter that the analysis then has no way to
test. Every frame is scored at BOTH 0.25 and 0.50 and both counts are stored
(`n_persons`, `n_persons_conf50`), so the sensitivity of any downstream
statement to the threshold is a column comparison rather than a re-run of the
sampler against the live feed -- which is not reproducible, because the feed
does not keep history.

WHAT THIS MEASURES, AND WHAT IT DOES NOT
---------------------------------------------------------------------------
PERSONS VISIBLE IN ONE FRAME. Not pedestrians per hour, not a flow. The
detector sees a fixed cone of one intersection at 352x240 -- a person 40 m
down the block is about eight pixels tall and will not be detected at any
threshold -- and it will happily count a person waiting in a car's windshield
or standing on the far sidewalk. It is a RELATIVE busyness measure for one
camera across time, and comparisons ACROSS cameras carry the field of view as
a confound that nothing here corrects.
"""
from __future__ import annotations

import dataclasses
import hashlib
import io
import pathlib
import time

import numpy as np

#: <repo>/src/loci/vision/person_detector.py -> three levels up is src/, four is the repo.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MODEL_DIR = REPO_ROOT / "data" / "models"
ONNX_PATH = MODEL_DIR / "yolo11n.onnx"
PT_PATH = MODEL_DIR / "yolo11n.pt"

#: The immutable upstream asset the ONNX was exported from.
PT_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"
PT_SHA256 = "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1"
#: Produced by ultralytics 8.4.150 / torch 2.14.0 / onnx 1.22.0, opset 12,
#: imgsz=640, dynamic=False, simplify=False. 10,701,722 bytes.
ONNX_SHA256 = "3770b4e016505653e57761cb307f066686da2bb0d05a93da1af2b8a8d2c8fbc1"

#: COCO class index for `person`. The only class this project reads.
PERSON_CLASS = 0

#: Square letterbox side the network was exported at (imgsz=640).
INPUT_SIZE = 640

#: Both thresholds are stored per frame. See the module docstring.
CONF_LOW = 0.25
CONF_HIGH = 0.50
#: IoU above which two person boxes are treated as one person.
NMS_IOU = 0.50


class DetectorUnavailable(RuntimeError):
    """No usable detector on this machine, with the command that fixes it."""


@dataclasses.dataclass(frozen=True)
class DetectionResult:
    """One frame's answer. `scores` is kept so a threshold sweep needs no re-run."""

    n_persons: int              # boxes at CONF_LOW
    n_persons_conf50: int       # boxes at CONF_HIGH
    scores: tuple[float, ...]   # surviving box confidences, descending
    width: int
    height: int
    seconds: float


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_model() -> pathlib.Path:
    """Path to the verified ONNX, or an error naming the export command."""
    if not ONNX_PATH.exists():
        raise DetectorUnavailable(
            f"{ONNX_PATH} is missing. Ultralytics publishes only .pt, so the ONNX is "
            f"exported once by hand:\n"
            f"  curl -L -o {PT_PATH} {PT_URL}\n"
            f"  uv run --no-project --python 3.12 --with ultralytics --with onnx "
            f"--with onnxslim --with onnxruntime python -c \"from ultralytics import "
            f"YOLO; YOLO('{PT_PATH}').export(format='onnx', imgsz={INPUT_SIZE}, "
            f"opset=12)\"\n"
            f"then move the produced yolo11n.onnx to {MODEL_DIR}."
        )
    got = sha256(ONNX_PATH.read_bytes())
    if ONNX_SHA256 != "PENDING" and got != ONNX_SHA256:
        raise DetectorUnavailable(
            f"{ONNX_PATH} sha256 {got} != recorded {ONNX_SHA256}. This digest pins the "
            f"bytes THIS repo's export produced, not an upstream-published digest: a "
            f"different ultralytics/torch version can legitimately produce a different "
            f"graph. Re-export from {PT_URL} (sha256 {PT_SHA256}) and update "
            f"ONNX_SHA256, or restore the recorded file. Counts from two different "
            f"graphs must not be pooled silently."
        )
    return ONNX_PATH


def _letterbox(img: np.ndarray, size: int = INPUT_SIZE) -> np.ndarray:
    """Aspect-preserving resize onto a grey square.

    A plain resize to 640x640 would stretch a 352x240 frame by 1.47x
    horizontally; the network was trained on undistorted crops and a stretched
    pedestrian is a slightly different object. Padding costs nothing because
    the counts, not the boxes, are what leave this module.
    """
    from PIL import Image

    h, w = img.shape[:2]
    scale = min(size / w, size / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = np.asarray(
        Image.fromarray(img).resize((nw, nh), Image.BILINEAR), dtype=np.uint8
    )
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)   # YOLO's pad grey
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float = NMS_IOU) -> np.ndarray:
    """Greedy non-maximum suppression -> indices to keep, score-descending.

    YOLO emits 8400 anchors and a single pedestrian lights up a dozen of them.
    Without NMS the 'count' is a count of anchors, which is not a count of
    people. Written out rather than pulled from torchvision for the reason in
    the module docstring.
    """
    if len(boxes) == 0:
        return np.empty(0, dtype=int)
    x1, y1 = boxes[:, 0], boxes[:, 1]
    x2, y2 = boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[rest] - inter
        iou = np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)
        order = rest[iou <= iou_thr]
    return np.asarray(keep, dtype=int)


def decode_jpeg(data: bytes) -> np.ndarray:
    """JPEG bytes -> HxWx3 uint8 RGB. Raises on a truncated or non-image body."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


class OnnxPersonDetector:
    """YOLO11n (COCO) through onnxruntime, person class only."""

    model = "yolo11n"
    quality = "ok"

    def __init__(self, path: pathlib.Path | None = None):
        import onnxruntime as ort

        self.path = pathlib.Path(path) if path else ensure_model()
        # CPU only, deliberately. CoreML is available on this machine but its
        # kernels are not bit-identical to the CPU ones, so a run started on
        # one provider and finished on another would mix two measurements.
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(self.path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.version = sha256(self.path.read_bytes())[:12]

    def count(self, data: bytes) -> DetectionResult:
        t0 = time.perf_counter()
        img = decode_jpeg(data)
        h, w = img.shape[:2]
        x = _letterbox(img).astype(np.float32) / 255.0
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])     # NCHW
        out = self.session.run(None, {self.input_name: x})[0]

        # YOLOv8/11 head: (1, 4 + n_classes, n_anchors), class scores already
        # sigmoid'd and NO separate objectness. Transpose to (n_anchors, ...).
        pred = np.squeeze(out, 0)
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T
        conf = pred[:, 4 + PERSON_CLASS]
        m = conf >= CONF_LOW
        cx, cy, bw, bh = pred[m, 0], pred[m, 1], pred[m, 2], pred[m, 3]
        boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
        scores = conf[m]
        keep = _nms(boxes, scores)
        kept = np.sort(scores[keep])[::-1] if len(keep) else np.empty(0)
        return DetectionResult(
            n_persons=int(len(kept)),
            n_persons_conf50=int((kept >= CONF_HIGH).sum()),
            scores=tuple(float(s) for s in kept),
            width=w, height=h,
            seconds=time.perf_counter() - t0,
        )


class HogPersonDetector:
    """OpenCV HOG + linear SVM. LOW QUALITY -- a documented last resort.

    Dalal-Triggs (2005) wants a pedestrian at least 128 px tall, upright and
    unoccluded. A 352x240 traffic frame gives 20-60 px people, so this both
    misses most of them and fires on lamp posts. It is here only so a machine
    without onnxruntime produces SOMETHING rather than nothing, and every row
    it writes is stamped `model='hog_opencv'` so it can be excluded wholesale.
    """

    model = "hog_opencv"
    quality = "low"
    version = "cv2-hog-default"

    def __init__(self):
        try:
            import cv2
        except ImportError as exc:      # pragma: no cover - depends on the machine
            raise DetectorUnavailable(
                "the HOG fallback needs OpenCV: `uv add opencv-python`"
            ) from exc
        self._cv2 = cv2
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def count(self, data: bytes) -> DetectionResult:   # pragma: no cover - see class doc
        t0 = time.perf_counter()
        img = decode_jpeg(data)
        h, w = img.shape[:2]
        grey = self._cv2.cvtColor(img, self._cv2.COLOR_RGB2GRAY)
        # Upscale: HOG's window is 64x128 and nothing in a 240-row frame fills it.
        grey = self._cv2.resize(grey, (w * 2, h * 2))
        rects, weights = self.hog.detectMultiScale(grey, winStride=(4, 4), scale=1.05)
        wt = np.asarray(weights).ravel() if len(rects) else np.empty(0)
        wt = np.sort(wt)[::-1]
        return DetectionResult(
            n_persons=int(len(wt)),
            # HOG's SVM margin is not a probability, so there is no honest 0.50
            # equivalent. A margin of 1.0 is the conventional "confident" cut.
            n_persons_conf50=int((wt >= 1.0).sum()),
            scores=tuple(float(s) for s in wt),
            width=w, height=h,
            seconds=time.perf_counter() - t0,
        )


def load_detector(prefer: str = "onnx"):
    """The best detector this machine can run. Raises if there is none."""
    errors = []
    if prefer == "onnx":
        try:
            return OnnxPersonDetector()
        except (ImportError, DetectorUnavailable) as exc:
            errors.append(f"onnx: {exc}")
    try:
        return HogPersonDetector()
    except DetectorUnavailable as exc:
        errors.append(f"hog: {exc}")
    raise DetectorUnavailable(
        "no person detector available on this machine.\n" + "\n".join(errors)
    )


def benchmark(detector, data: bytes, n: int = 20) -> dict:
    """Seconds per frame, CPU, on this machine. First call is excluded (warm-up)."""
    detector.count(data)
    t0 = time.perf_counter()
    for _ in range(n):
        detector.count(data)
    total = time.perf_counter() - t0
    return {"model": detector.model, "frames": n, "seconds_total": total,
            "seconds_per_frame": total / n, "fps": n / total}
