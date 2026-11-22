"""Preprocess one REFIT house CSV and run standalone model inference."""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .inference import load
    from .preprocess import load_house
except ImportError:
    from inference import load
    from preprocess import load_house


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--house", type=int, required=True, choices=(2, 3, 5, 6))
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--window-index", type=int, default=0)
    args = parser.parse_args()
    x, _, starts, _ = load_house(args.csv, args.house)
    if not 0 <= args.window_index < len(x):
        raise IndexError(f"window index {args.window_index} outside 0..{len(x)-1}")
    model = load(args.checkpoint)
    predicted_w = model.predict(x[args.window_index:args.window_index + 1])
    print({
        "house": args.house,
        "window_start": str(starts[args.window_index]),
        "labels": model.labels,
        "shape": predicted_w.shape,
        "mean_w": predicted_w.mean(axis=-1).round(2).tolist(),
    })


if __name__ == "__main__":
    main()
