from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Write minimal training-like smoke artifacts.")
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--ckpt-dir", default="ckpts")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    ckpt_dir = Path(args.ckpt_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = output_dir / "metrics.jsonl"
    steps = max(args.steps, 1)
    for step in range(1, steps + 1):
        record = {
            "step": step,
            "loss": round(1.0 / step, 4),
            "accuracy": round(step / steps, 4),
        }
        with metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        print(
            f"step={record['step']} loss={record['loss']} accuracy={record['accuracy']}",
            flush=True,
        )
        time.sleep(max(args.sleep, 0.0))

    summary = {
        "status": "ok",
        "steps": steps,
        "metrics_path": metrics_path.as_posix(),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (ckpt_dir / "last.ckpt").write_text("fake checkpoint\n", encoding="utf-8")
    print("servertool smoke train complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
