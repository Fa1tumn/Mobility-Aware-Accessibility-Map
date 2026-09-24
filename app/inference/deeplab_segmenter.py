from pathlib import Path

from mmseg.apis import MMSegInferencer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_PATH = Path(__file__).resolve().parent / "example_photo" / "bus.jpg"
WEIGHTS_PATH = (
    PROJECT_ROOT
    / "models"
    / "deeplab"
    / "deeplabv3plus_r18-d8_512x1024_80k_cityscapes_20201226_080942-cff257fe.pth"
)

inferencer = MMSegInferencer(
    model="deeplabv3plus_r18-d8_4xb2-80k_cityscapes-512x1024",
    weights=str(WEIGHTS_PATH),
)

inferencer(
    str(IMAGE_PATH),
    out_dir=str(PROJECT_ROOT / "output" / "deeplab"),
    show=False,
)
