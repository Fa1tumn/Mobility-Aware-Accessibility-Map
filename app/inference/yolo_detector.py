from ultralytics import YOLO




class YOLODetector:
    def __init__(self, model_path: str = "yolov8n.pt"):
        self.model = YOLO(model_path)  # load a pretrained YOLOv8n model

    def predict(self, source: str):
        results = self.model.predict(source=source, show=True)  # predict on an image
        return results

if __name__ == "__main__":
    detector = YOLODetector("../models/yolov8n.pt")  # replace with your model path
    results = detector.predict("./app/inference/example_photo/bus.jpg")  # replace with your image path
    print(results) 
    for index, result in enumerate(results):
        result.save(f"./output/yolo_detection/result_{index}.jpg")  # save the result image