import json

import numpy as np

from yolov11.roboflow_video import annotate, read_cache


def test_preview_cache_reads_do_not_change_the_file(tmp_path):
    path = tmp_path / "predictions.jsonl"
    complete = {"frame_index": 0, "result": {"predictions": []}}
    content = json.dumps(complete) + '\n{"frame_index": 1'
    path.write_text(content, encoding="utf-8")
    assert read_cache(path) == {0: complete}
    assert path.read_text(encoding="utf-8") == content


def test_prediction_boxes_are_scaled_to_video_resolution():
    frame = np.zeros((80, 160, 3), dtype=np.uint8)
    record = {
        "frame_index": 0,
        "result": {
            "image": {"width": 80, "height": 40},
            "predictions": [{"x": 40, "y": 20, "width": 20, "height": 10, "class": "necesita rampa", "confidence": 0.9, "class_id": 0}],
        },
    }
    result = annotate(frame, record, "accesibility-street/11")
    assert result.shape == (80, 160, 3)
    assert result[40, 100].tolist() == [65, 210, 70]
    assert record["result"]["predictions"][0]["class"] == "necesita rampa"
