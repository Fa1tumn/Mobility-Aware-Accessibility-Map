from pathlib import Path
import torch
from ultralytics import YOLO

MODEL_PATH = Path(__file__).resolve().parent.parent[2] / "models" / "yolov8n.pt"
DATASET_PATH = Path(__file__).resolve().parent.parent[2] / "datasets" / "custom_dataset.yaml"
OUTPUT_PATH = Path(__file__).resolve().parent.parent[2] / "output" / "finetuning"

def finetune_yolo(model_path: str = str(MODEL_PATH), dataset_path: str = str(DATASET_PATH), output_path: str = str(OUTPUT_PATH)):
    use_cuda = torch.cuda.is_available()

    model = YOLO(model_path)

    model.train(
        data=dataset_path,
        epochs=100,
        imgsz=640,
        batch=16,
        device=0 if use_cuda else -1,
        workers=4,
        pretrained=True,
        patience=10,
        project=output_path,
        name="yolov8n_finetuned",
    )

if __name__ == "__main__":
    finetune_yolo(MODEL_PATH, DATASET_PATH, OUTPUT_PATH)