"""Joe's face finder. Runs inside the private "faces" environment (NOT Joe's own Python).

    python face_worker.py <yunet.onnx> <picture>   ->  prints {"ok": true, "w": W, "h": H, "faces": [[x, y, w, h, score], ...]}

YuNet (OpenCV Zoo, MIT license, about 230 KB) is a small face detector made for exactly this: it finds every
face, adults and children alike, on the processor in well under a second. The picture is looked at three
ways and the answers merged: at a size the detector likes, at a bigger size (small faces in the background),
and mirrored (faces turned to one side). Coordinates are in pixels of the original picture.
"""
import json
import os as _os
import sys as _sys

# Never import Joe's own modules in place of the standard library.
_here = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:] = [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import sys

SCORE = 0.6        # lower than OpenCV's 0.9 example: for blurring, a missed face is worse than an extra blur
NMS = 0.3
BIG_SCORE = 0.75   # the enlarged pass sees "faces" in hands and knees (0.67 on the porch photo, dev26),
SMALL = 0.04       # so there it must be surer, unless the box is tiny (a far-away face, under 4% of the long side)


def _detect(cv2, model, img, scale, flip=False):
    h, w = img.shape[:2]
    pic = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA
                     if scale < 1 else cv2.INTER_CUBIC)
    if flip:
        pic = cv2.flip(pic, 1)
    ph, pw = pic.shape[:2]
    det = cv2.FaceDetectorYN.create(model, "", (pw, ph), SCORE, NMS, 5000)
    _, faces = det.detect(pic)
    out = []
    for f in (faces if faces is not None else []):
        x, y, fw, fh, score = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])
        if flip:
            x = pw - x - fw
        out.append([x / scale, y / scale, fw / scale, fh / scale, score])
    return out


def _iou(a, b):
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    ix, iy = max(0.0, min(ax2, bx2) - max(a[0], b[0])), max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def merge(found):
    """One box per face: of overlapping boxes, keep the surest."""
    keep = []
    for f in sorted(found, key=lambda f: -f[4]):
        if all(_iou(f, k) < 0.35 for k in keep):
            keep.append(f)
    return keep


def find_faces(model, path):
    import cv2
    import numpy as np
    data = np.fromfile(path, dtype=np.uint8)            # works with any characters in the path (Windows)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("couldn't read that picture")
    h, w = img.shape[:2]
    base = min(1.0, 1920 / max(w, h))                   # the usual pass, at most 1920 px on the long side
    found = _detect(cv2, model, img, base) + _detect(cv2, model, img, base, flip=True)
    big = min(2.0, 3200 / max(w, h))                    # small, far-away faces
    if big > base * 1.3:
        found += [f for f in _detect(cv2, model, img, big)
                  if f[4] >= BIG_SCORE or max(f[2], f[3]) < SMALL * max(w, h)]
    return w, h, merge(found)


def main(argv):
    if len(argv) != 3:
        print(json.dumps({"ok": False, "error": "usage: face_worker.py <model.onnx> <picture>"}))
        return 2
    try:
        w, h, faces = find_faces(argv[1], argv[2])
    except Exception as e:  # noqa: BLE001 (any trouble goes back to Joe as a message)
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps({"ok": True, "w": w, "h": h, "faces": [[round(v, 1) for v in f] for f in faces]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
