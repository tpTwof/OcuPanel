"""Hash local model and processor artifacts without downloading or changing them."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path


def freeze(root: Path, description: dict) -> dict:
    required = ("classification_revision", "segmentation_revision", "class_order", "mask_semantics", "processor", "cdr_definition")
    if any(not description.get(field) for field in required):
        raise ValueError(f"Baseline description must include {', '.join(required)}")
    if any(not re.fullmatch(r"[0-9a-fA-F]{40}", description[field])
           for field in ("classification_revision", "segmentation_revision")):
        raise ValueError("Model revisions must be pinned 40-character commit hashes")
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        files.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                      "sha256": digest.hexdigest(), "symlink": path.is_symlink()})
    if not files:
        raise ValueError("No local model artifacts found")
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "description": description, "artifacts": files, "validation": "not_evaluated"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--description", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.artifacts.resolve(strict=True)
    if not root.is_dir() or args.output.resolve().is_relative_to(root):
        raise ValueError("Artifacts must be a directory and output must be outside it")
    result = freeze(root, json.loads(args.description.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
