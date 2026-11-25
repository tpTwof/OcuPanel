"""Offline archive maintenance for a stopped OcuPanel installation."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from report import assets


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive_files(root: Path):
    for folder, pattern in (("original_store", r"[0-9a-f]{32}\.bin"), ("img_store", r"[0-9a-f]{32}\.jpg")):
        directory = root / folder
        if not directory.exists():
            continue
        if directory.resolve().parent != root.resolve():
            raise ValueError(f"Linked asset directory: {folder}")
        for path in directory.iterdir():
            if re.fullmatch(pattern, path.name) and path.is_file():
                if path.resolve().parent != directory.resolve() or path.is_symlink():
                    raise ValueError(f"Linked asset: {path.name}")
                yield path.relative_to(root)


def materialize(source: Path, destination: Path, *, restore: bool) -> None:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("Choose a new destination outside the source directory")
    database = source / "ocupanel.db"
    if not database.is_file() or database.is_symlink():
        raise ValueError("Missing archive database")
    with tempfile.TemporaryDirectory(dir=destination.parent) as work:
        stage = Path(work) / "archive"
        stage.mkdir()
        files = list(archive_files(source))
        if restore:
            manifest = json.loads((source / "sha256.json").read_text(encoding="utf8"))
            expected = {rel.as_posix() for rel in files} | {"ocupanel.db"}
            if set(manifest) != expected:
                raise ValueError("Archive file list differs from its manifest")
            shutil.copyfile(database, stage / database.name)
        else:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(stage / database.name)) as dst:
                src.backup(dst)
        for rel in files:
            (stage / rel.parent).mkdir(exist_ok=True)
            shutil.copyfile(source / rel, stage / rel)
        files.append(Path(database.name))
        actual = {rel.as_posix(): checksum(stage / rel) for rel in files}
        if restore and actual != manifest:
            raise ValueError("Archive checksum mismatch")
        with closing(sqlite3.connect(stage / database.name)) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Database integrity check failed")
        if not restore:
            (stage / "sha256.json").write_text(json.dumps(actual, indent=2), encoding="utf8")
        stage.rename(destination)


def expire_originals(root: Path, days: int, apply: bool) -> int:
    return assets.expire_originals(root / "ocupanel.db", root / "original_store", days, apply)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("backup", "restore"):
        command = commands.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("destination", type=Path)
    expire = commands.add_parser("expire")
    expire.add_argument("source", type=Path)
    expire.add_argument("--days", required=True, type=int)
    expire.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.action == "expire":
        print("Expired originals:", expire_originals(args.source, args.days, args.apply))
    else:
        materialize(args.source, args.destination, restore=args.action == "restore")
