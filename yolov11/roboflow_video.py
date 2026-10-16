import argparse
import json
import logging
import os
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from dotenv import load_dotenv
from inference_sdk import InferenceConfiguration, InferenceHTTPClient


ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "necesita rampa": "Ramp needed",
    "dificulta el paso": "Passage obstructed",
    "suelo inestable": "Unstable ground",
    "inaccesible por obras": "Construction blockage",
    "rampa inaccesible": "Inaccessible ramp",
}


def read_cache(path):
    records = {}
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            try:
                record = json.loads(line)
            except ValueError:
                if index == len(lines) - 1:
                    break
                raise ValueError("Invalid prediction cache.") from None
            records[record["frame_index"]] = record
    return records


def infer_frames(args, info, records, cache_path):
    key = os.getenv("ROBOFLOW_API_KEY", "").strip()
    if not key:
        raise ValueError("Set ROBOFLOW_API_KEY in .env.")
    cache_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records.values()), encoding="utf-8")
    logging.getLogger("inference_sdk").setLevel(logging.CRITICAL)
    client = InferenceHTTPClient(api_url="https://serverless.roboflow.com", api_key=key).configure(
        InferenceConfiguration(api_key_transport="header", confidence_threshold=args.confidence)
    )
    capture = cv2.VideoCapture(str(args.source))
    started = time.monotonic()
    completed_before = sum(index < info["frames"] for index in records)
    last_update = started

    def predict(index, image):
        try:
            result = client.infer(image, model_id=args.model)
        except Exception as error:
            message = str(error).replace(key, "[hidden]")
            raise RuntimeError(f"Frame {index}: {message}") from None
        if not isinstance(result, dict) or not isinstance(result.get("predictions"), list):
            raise ValueError(f"Frame {index}: expected an object-detection response.")
        return {"frame_index": index, "time_seconds": index / info["fps"], "result": result}

    try:
        with cache_path.open("a", encoding="utf-8") as output, ThreadPoolExecutor(max_workers=args.workers) as executor:
            index = 0
            while index < info["frames"]:
                futures = []
                for _ in range(args.workers * 4):
                    if index >= info["frames"]:
                        break
                    ok, frame = capture.read()
                    if not ok:
                        raise RuntimeError(f"Video decoding stopped at frame {index}.")
                    if index not in records:
                        ratio = min(1, args.max_size / max(frame.shape[:2]))
                        if ratio < 1:
                            frame = cv2.resize(frame, (round(frame.shape[1] * ratio), round(frame.shape[0] * ratio)))
                        futures.append(executor.submit(predict, index, frame))
                    index += 1
                for future in as_completed(futures):
                    record = future.result()
                    records[record["frame_index"]] = record
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
                    output.flush()
                    now = time.monotonic()
                    if now - last_update >= 5 or len(records) == info["frames"]:
                        count = sum(index < info["frames"] for index in records)
                        speed = (count - completed_before) / max(now - started, 0.001)
                        remaining = (info["frames"] - count) / speed if speed else 0
                        print(f"Inferred {count}/{info['frames']} frames | {speed:.2f} FPS | ETA {remaining / 60:.1f} min", flush=True)
                        last_update = now
    finally:
        capture.release()


def annotate(frame, record, model):
    result = record["result"]
    width = result.get("image", {}).get("width", frame.shape[1])
    height = result.get("image", {}).get("height", frame.shape[0])
    scale_x, scale_y = frame.shape[1] / width, frame.shape[0] / height
    colors = [(65, 210, 70), (0, 190, 255), (230, 100, 40), (200, 80, 220), (80, 220, 220)]
    for prediction in result["predictions"]:
        color = colors[int(prediction.get("class_id", 0)) % len(colors)]
        x = prediction["x"] * scale_x
        y = prediction["y"] * scale_y
        w = prediction["width"] * scale_x
        h = prediction["height"] * scale_y
        left, top = max(0, round(x - w / 2)), max(0, round(y - h / 2))
        right, bottom = min(frame.shape[1] - 1, round(x + w / 2)), min(frame.shape[0] - 1, round(y + h / 2))
        if prediction.get("points"):
            polygon = np.array([[round(point["x"] * scale_x), round(point["y"] * scale_y)] for point in prediction["points"]], dtype=np.int32)
            cv2.polylines(frame, [polygon], True, color, 2)
        cv2.rectangle(frame, (left, top), (right, bottom), color, 3)
        name = LABELS.get(prediction["class"], f"Class {prediction.get('class_id', 0)}")
        label = f"{name} {prediction['confidence']:.2f}"
        (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        label_x = max(0, min(left, frame.shape[1] - text_width - 8))
        label_y = max(text_height + 8, top)
        cv2.rectangle(frame, (label_x, label_y - text_height - 8), (min(frame.shape[1] - 1, label_x + text_width + 8), label_y), color, -1)
        cv2.putText(frame, label, (label_x + 4, label_y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (15, 15, 15), 2, cv2.LINE_AA)
    position = (18, frame.shape[0] - 16)
    cv2.putText(frame, f"{model} | Frame {record['frame_index'] + 1}", position, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(frame, f"{model} | Frame {record['frame_index'] + 1}", position, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return frame


def render_video(args, info, records):
    if any(index not in records for index in range(info["frames"])):
        raise ValueError("Prediction cache is incomplete. Run inference before rendering.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_name(args.output.stem + ".partial.mp4")
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{info['width']}x{info['height']}",
        "-r", str(info["fps"]), "-i", "-", "-i", str(args.source),
        "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
        "-t", str(info["frames"] / info["fps"]), str(partial),
    ]
    capture = cv2.VideoCapture(str(args.source))
    sample_frames = {0, info["frames"] // 4, info["frames"] // 2, 3 * info["frames"] // 4, info["frames"] - 1}
    sample_frames.add(max(range(info["frames"]), key=lambda index: len(records[index]["result"]["predictions"])))
    log_path = args.cache_dir / "encoding.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
        try:
            for index in range(info["frames"]):
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError(f"Rendering stopped at frame {index}.")
                frame = annotate(frame, records[index], args.model)
                process.stdin.write(frame.tobytes())
                if index in sample_frames:
                    cv2.imwrite(str(args.cache_dir / f"preview_{index:05d}.jpg"), frame)
                if (index + 1) % 500 == 0 or index + 1 == info["frames"]:
                    print(f"Rendered {index + 1}/{info['frames']} frames", flush=True)
        finally:
            capture.release()
            process.stdin.close()
            status = process.wait()
    if status != 0:
        raise RuntimeError(f"Video encoding failed. See {log_path}.")
    check = cv2.VideoCapture(str(partial))
    written = int(check.get(cv2.CAP_PROP_FRAME_COUNT))
    check.release()
    if written != info["frames"]:
        raise RuntimeError(f"Output has {written} frames; expected {info['frames']}.")
    partial.replace(args.output)
    counts = Counter(prediction["class"] for index in range(info["frames"]) for prediction in records[index]["result"]["predictions"])
    labels = {prediction["class"]: LABELS.get(prediction["class"], f"Class {prediction.get('class_id', 0)}") for index in range(info["frames"]) for prediction in records[index]["result"]["predictions"]}
    summary = {**info, "model": args.model, "confidence": args.confidence, "prediction_count_by_class": dict(counts), "display_labels": labels, "output": str(args.output)}
    (args.cache_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Saved: {args.output} ({written} frames)", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "yolov11/example.mp4")
    parser.add_argument("--output", type=Path, default=ROOT / "yolov11/roboflow_output.mp4")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "output/roboflow/accesibility-street-v11")
    parser.add_argument("--model", default="accesibility-street/11")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--max-size", type=int, default=960)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--infer-only", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    if args.workers < 1 or args.max_size < 32 or not 0 <= args.confidence <= 1 or (args.limit is not None and args.limit < 1):
        parser.error("Check workers, max-size, confidence and limit.")
    if args.render_only and args.infer_only:
        parser.error("Choose either --render-only or --infer-only.")
    capture = cv2.VideoCapture(str(args.source))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    info = {"fps": capture.get(cv2.CAP_PROP_FPS), "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)), "frames": min(total, args.limit) if args.limit else total}
    capture.release()
    if not all(value > 0 for value in info.values()):
        parser.error("Cannot read the source video.")
    if args.source.resolve() == args.output.resolve():
        parser.error("Source and output must be different files.")
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = args.cache_dir / "metadata.json"
    metadata = {"source": str(args.source.resolve()), "source_size": args.source.stat().st_size, "source_mtime_ns": args.source.stat().st_mtime_ns, "model": args.model, "confidence": args.confidence, "max_size": args.max_size}
    if metadata_path.exists() and json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
        parser.error("Cache settings differ. Use a separate --cache-dir.")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Input: {args.source} | {info['width']}x{info['height']} | {info['frames']} frames | {info['fps']:.4f} FPS", flush=True)
    try:
        cache_path = args.cache_dir / "predictions.jsonl"
        records = read_cache(cache_path)
        print(f"Cached predictions: {len(records)}", flush=True)
        if not args.render_only:
            infer_frames(args, info, records, cache_path)
        if not args.infer_only:
            render_video(args, info, records)
    except Exception as error:
        key = os.getenv("ROBOFLOW_API_KEY", "")
        message = str(error).replace(key, "[hidden]") if key else str(error)
        parser.exit(1, f"Inference failed: {message}\n")


if __name__ == "__main__":
    main()
