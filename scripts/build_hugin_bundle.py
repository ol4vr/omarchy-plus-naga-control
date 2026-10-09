#!/usr/bin/env python3
"""Create a deterministic, FUSE-free Hugin AppDir archive and inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

BASELINE = "f48b3a4374b27571ab2afabe8e999595483e138a"
OPENRAZER = "26b0eeb5ed70d638fa3528851adcd5e58369a7f5"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _normalized(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 0
    return info


def build(appdir: Path, output: Path) -> dict[str, object]:
    required = (
        "AppRun",
        "usr/share/naga-control/system/systemd/user/naga-control.service",
        "usr/share/naga-control/system/dbus-1/services/org.nagacontrol.Service1.service",
        "usr/share/naga-control/system/desktop/org.nagacontrol.NagaControl.desktop",
    )
    for relative in required:
        if not (appdir / relative).is_file():
            raise ValueError(f"incomplete AppDir: missing {relative}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:xz", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted((appdir, *appdir.rglob("*")), key=lambda item: item.as_posix()):
            relative = path.relative_to(appdir)
            archive_name = Path("Naga-Control.AppDir") / relative
            archive.add(path, arcname=archive_name.as_posix(), recursive=False, filter=_normalized)
    packages = sorted(
        path.name.removesuffix(".dist-info")
        for path in appdir.glob("usr/lib/python*/site-packages/*.dist-info")
    )
    result: dict[str, object] = {
        "schema": 1,
        "artifact": output.name,
        "sha256": digest(output),
        "size": output.stat().st_size,
        "source_baseline": BASELINE,
        "openrazer_cohort": OPENRAZER,
        "format": "AppDir tar.xz; extracted execution; FUSE2 not required",
        "platform": "Hugin x86_64; no Ubuntu portability claim",
        "python_distributions": packages,
    }
    output.with_suffix(output.suffix + ".json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("appdir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build(args.appdir.resolve(), args.output.resolve())
    print(f"{result['sha256']}  {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
