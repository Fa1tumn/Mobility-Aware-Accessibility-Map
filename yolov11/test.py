"""Run YOLO inference on a video and save the annotated result as MP4."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO


HERE = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=HERE / "best.pt")
    parser.add_argument("--source", type=Path, default=HERE / "example.mp4")
    parser.add_argument("--output", type=Path, default=HERE / "output.mp4")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument(
        "--device",
        default=None,
        help="Inference device, e.g. 0, 0,1, or cpu (default: CUDA 0 if available)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    device = args.device or ("0" if torch.cuda.is_available() else "cpu")

    if not args.model.is_file():
        raise FileNotFoundError(f"Model not found: {args.model}")
    if not args.source.is_file():
        raise FileNotFoundError(f"Input video not found: {args.source}")

    capture = cv2.VideoCapture(str(args.source))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open input video: {args.source}")

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.release()
    if fps <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("The input video has invalid FPS or dimensions")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(args.output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Unable to create output video: {args.output}")

    print(f"Device: {device}")
    if device != "cpu":
        gpu_index = int(str(device).split(",")[0])
        print(f"GPU: {torch.cuda.get_device_name(gpu_index)}")
    print(f"Input: {args.source} ({width}x{height}, {fps:.2f} FPS, {frame_count} frames)")

    model = YOLO(str(args.model))
    results = model.predict(
        source=str(args.source),
        conf=args.conf,
        imgsz=args.imgsz,
        device=device,
        stream=True,
        verbose=False,
    )

    written = 0
    try:
        for written, result in enumerate(results, start=1):
            annotated = result.plot()
            if annotated.shape[1] != width or annotated.shape[0] != height:
                annotated = cv2.resize(annotated, (width, height))
            writer.write(annotated)
            if written % 100 == 0 or written == frame_count:
                print(f"Processed {written}/{frame_count} frames")
    finally:
        writer.release()

    if written == 0:
        args.output.unlink(missing_ok=True)
        raise RuntimeError("Inference produced no frames")
    print(f"Saved: {args.output} ({written} frames)")


if __name__ == "__main__":
    main()
