"""从 backend 运行 python -m vision IMAGE --output overlay.png。"""
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="视杯视盘分割测试")
    parser.add_argument("image")
    parser.add_argument("--output", default="overlay.png")
    parser.add_argument("--device", default=None)
    args = parser.parse_args()
    import cv2
    from .anatomy.optic_disc_cup import analyze_optic_disc_cup
    overlay, cdr = analyze_optic_disc_cup(args.image, device=args.device)
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("PNG encoding failed")
    Path(args.output).write_bytes(encoded.tobytes())
    print(f"CDR: {cdr:.4f}")
    print(f"Overlay: {Path(args.output).resolve()}")

if __name__ == "__main__":
    main()
