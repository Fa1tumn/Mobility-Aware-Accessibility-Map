from app.inference.yolo_detector import YOLODetector

objects = YOLODetector()
objects.predict("./example_photo/bus.jpg")  # replace with your image path