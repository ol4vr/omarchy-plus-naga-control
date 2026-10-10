#!/usr/bin/env python3
"""Stage, explicitly activate, or remove the owned FUSE-free user bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, cast

STATE_RELATIVE = Path(".local/share/naga-control/owned-install.json")
APP_ROOT_RELATIVE = Path(".local/opt/naga-control")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _write_atomic(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=".naga-control-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_state(home: Path) -> dict[str, Any]:
    path = home / STATE_RELATIVE
    if not path.is_file():
        raise RuntimeError("no owned Naga Control stage is present")
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("invalid owned installation state")
    mapping = cast(dict[str, object], value)
    if mapping.get("schema") != 1:
        raise RuntimeError("invalid owned installation state")
    return cast(dict[str, Any], mapping)


def _safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != "Naga-Control.AppDir"
            or member.issym()
            or member.islnk()
            or member.isdev()
        ):
            raise RuntimeError(f"unsafe bundle member: {member.name}")
    return members


def _verified_bundle(bundle: Path, expected_sha256: str) -> str:
    actual = digest(bundle)
    if actual != expected_sha256.lower() or len(expected_sha256) != 64:
        raise RuntimeError("bundle SHA-256 mismatch")
    return actual


def _extract_stage(home: Path, bundle: Path, actual: str) -> Path:
    target = home / APP_ROOT_RELATIVE / actual / "Naga-Control.AppDir"
    if target.exists():
        raise RuntimeError("untracked stage target already exists")
    target.parent.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(bundle, "r:xz") as archive:
            members = _safe_members(archive)
            archive.extractall(target.parent, members=members, filter="data")
        required = (
            target / "AppRun",
            target / "usr/share/naga-control/system/systemd/user/naga-control.service",
            target
            / "usr/share/naga-control/system/dbus-1/services/org.nagacontrol.Service1.service",
        )
        if not all(path.is_file() for path in required):
            raise RuntimeError("bundle is missing required application or integration files")
    except BaseException:
        shutil.rmtree(target.parent, ignore_errors=True)
        raise
    return target


def _state(appdir: Path, actual: str, active_files: dict[str, str]) -> dict[str, Any]:
    return {
        "schema": 1,
        "bundle_sha256": actual,
        "appdir": str(appdir),
        "active_files": active_files,
    }


def _store_state(home: Path, state: dict[str, Any]) -> None:
    _write_atomic(
        home / STATE_RELATIVE, (json.dumps(state, indent=2, sort_keys=True) + "\n").encode()
    )


def stage(home: Path, bundle: Path, expected_sha256: str) -> Path:
    home = home.resolve()
    actual = _verified_bundle(bundle, expected_sha256)
    state_path = home / STATE_RELATIVE
    if state_path.exists():
        current = _load_state(home)
        if current.get("bundle_sha256") == actual:
            return Path(str(current["appdir"]))
        raise RuntimeError("another owned Naga Control stage already exists")
    target = _extract_stage(home, bundle, actual)
    try:
        _store_state(home, _state(target, actual, {}))
    except BaseException:
        shutil.rmtree(target.parent, ignore_errors=True)
        raise
    return target


def _assert_discovery_configuration(home: Path) -> None:
    config = home / ".config/naga-control/config.toml"
    if not config.exists():
        return
    value = tomllib.loads(config.read_text(encoding="utf-8"))
    if value.get("hardware_writes", False) is not False:
        raise RuntimeError("activation requires hardware_writes = false")
    if value.get("remapping_enabled", False) is not False:
        raise RuntimeError("activation requires remapping_enabled = false")
    profiles: object = value.get("profiles", {})
    if isinstance(profiles, dict):
        for name, profile in cast(dict[str, object], profiles).items():
            if (
                isinstance(profile, dict)
                and cast(dict[str, object], profile).get("lighting_writes", False) is not False
            ):
                raise RuntimeError(f"activation requires profiles.{name}.lighting_writes = false")


def _activation_payload(home: Path, appdir: Path) -> dict[Path, bytes]:
    system = appdir / "usr/share/naga-control/system"
    wrapper = f'#!/usr/bin/env bash\nexec "{appdir / "AppRun"}" "$@"\n'.encode()
    service_wrapper = f'#!/usr/bin/env bash\nexec "{appdir / "AppRun"}" service "$@"\n'.encode()
    return {
        home / ".local/bin/naga-control": wrapper,
        home / ".local/bin/naga-control-service": service_wrapper,
        home / ".config/systemd/user/naga-control.service": (
            system / "systemd/user/naga-control.service"
        ).read_bytes(),
        home / ".local/share/dbus-1/services/org.nagacontrol.Service1.service": (
            system / "dbus-1/services/org.nagacontrol.Service1.service"
        ).read_bytes(),
        home / ".local/share/applications/org.nagacontrol.NagaControl.desktop": (
            system / "desktop/org.nagacontrol.NagaControl.desktop"
        ).read_bytes(),
    }


def _verified_active_files(
    state: dict[str, Any], *, require_present: bool = True
) -> dict[Path, str]:
    raw_active: object = state.get("active_files", {})
    if not isinstance(raw_active, dict):
        raise RuntimeError("invalid active-file manifest")
    entries = cast(dict[object, object], raw_active)
    if not all(
        isinstance(name, str) and isinstance(expected, str) for name, expected in entries.items()
    ):
        raise RuntimeError("invalid active-file manifest")
    active = cast(dict[str, str], raw_active)
    files = {Path(name): expected for name, expected in active.items()}
    for path, expected in files.items():
        if path.exists() and digest(path) != expected:
            raise RuntimeError(f"installer-owned file was modified; preserving it: {path}")
        if require_present and not path.is_file():
            raise RuntimeError(f"installer-owned file was removed; preserving state: {path}")
    return files


def _is_service_active(systemctl: str) -> bool:
    probe = subprocess.run(
        [systemctl, "--user", "is-active", "--quiet", "naga-control.service"], check=False
    )
    if probe.returncode not in {0, 3}:
        raise RuntimeError(f"unable to determine Naga Control service state: {probe.returncode}")
    return probe.returncode == 0


def _start_service(systemctl: str) -> None:
    subprocess.run([systemctl, "--user", "start", "naga-control.service"], check=True)
    if not _is_service_active(systemctl):
        raise RuntimeError("Naga Control service did not remain active after start")


def upgrade(home: Path, bundle: Path, expected_sha256: str, systemctl: str = "systemctl") -> Path:
    home = home.resolve()
    _assert_discovery_configuration(home)
    previous_state = _load_state(home)
    active_files = _verified_active_files(previous_state)
    actual = _verified_bundle(bundle, expected_sha256)
    if previous_state.get("bundle_sha256") == actual:
        return Path(str(previous_state["appdir"]))

    target = _extract_stage(home, bundle, actual)
    previous_appdir = Path(str(previous_state["appdir"]))
    previous_payload = {
        path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in active_files
    }
    replacement = _activation_payload(home, target) if active_files else {}
    if active_files and set(active_files) != set(replacement):
        shutil.rmtree(target.parent, ignore_errors=True)
        raise RuntimeError("active-file manifest does not match the current installer contract")

    was_active = False
    try:
        if active_files:
            was_active = _is_service_active(systemctl)
            if was_active:
                subprocess.run([systemctl, "--user", "stop", "naga-control.service"], check=True)
            for path, data in replacement.items():
                _write_atomic(path, data, 0o755 if path.parent.name == "bin" else 0o644)
        hashes = {str(path): hashlib.sha256(data).hexdigest() for path, data in replacement.items()}
        _store_state(home, _state(target, actual, hashes))
        if active_files:
            subprocess.run([systemctl, "--user", "daemon-reload"], check=True)
            if was_active:
                _start_service(systemctl)
    except BaseException as failure:
        rollback_errors: list[BaseException] = []
        if active_files:
            try:
                subprocess.run([systemctl, "--user", "stop", "naga-control.service"], check=False)
            except BaseException as exc:
                rollback_errors.append(exc)
            for path, (data, mode) in previous_payload.items():
                try:
                    _write_atomic(path, data, mode)
                except BaseException as exc:
                    rollback_errors.append(exc)
        try:
            _store_state(home, previous_state)
            if active_files:
                subprocess.run([systemctl, "--user", "daemon-reload"], check=True)
                if was_active:
                    _start_service(systemctl)
        except BaseException as exc:
            rollback_errors.append(exc)
        shutil.rmtree(target.parent, ignore_errors=True)
        if rollback_errors:
            raise RuntimeError(
                f"upgrade failed ({failure}); rollback also failed ({rollback_errors[0]})"
            ) from failure
        raise

    shutil.rmtree(previous_appdir.parent, ignore_errors=True)
    return target


def activate(home: Path, systemctl: str = "systemctl") -> None:
    home = home.resolve()
    _assert_discovery_configuration(home)
    state = _load_state(home)
    appdir = Path(str(state["appdir"]))
    payload = _activation_payload(home, appdir)
    if state.get("active_files"):
        raise RuntimeError("owned Naga Control integration is already active")
    for path in payload:
        if path.exists():
            raise RuntimeError(f"refusing to replace unowned file: {path}")
    written: list[Path] = []
    try:
        for path, data in payload.items():
            _write_atomic(path, data, 0o755 if path.parent.name == "bin" else 0o644)
            written.append(path)
        state["active_files"] = {
            str(path): hashlib.sha256(data).hexdigest() for path, data in payload.items()
        }
        _write_atomic(
            home / STATE_RELATIVE, (json.dumps(state, indent=2, sort_keys=True) + "\n").encode()
        )
        subprocess.run([systemctl, "--user", "daemon-reload"], check=True)
        subprocess.run([systemctl, "--user", "start", "naga-control.service"], check=True)
    except BaseException:
        subprocess.run([systemctl, "--user", "stop", "naga-control.service"], check=False)
        for path in reversed(written):
            path.unlink(missing_ok=True)
        state["active_files"] = {}
        _write_atomic(
            home / STATE_RELATIVE, (json.dumps(state, indent=2, sort_keys=True) + "\n").encode()
        )
        raise


def remove(home: Path, systemctl: str = "systemctl", purge_stage: bool = False) -> None:
    home = home.resolve()
    state = _load_state(home)
    active = _verified_active_files(state, require_present=False)
    if active:
        probe = subprocess.run(
            [systemctl, "--user", "is-active", "--quiet", "naga-control.service"], check=False
        )
        if probe.returncode == 0:
            raise RuntimeError(
                "service is active; stop it under separate authorization before removal"
            )
    for path in active:
        path.unlink(missing_ok=True)
    state["active_files"] = {}
    if active:
        subprocess.run([systemctl, "--user", "daemon-reload"], check=True)
    if purge_stage:
        shutil.rmtree(Path(str(state["appdir"])).parent)
        (home / STATE_RELATIVE).unlink()
    else:
        _write_atomic(
            home / STATE_RELATIVE, (json.dumps(state, indent=2, sort_keys=True) + "\n").encode()
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    staging = commands.add_parser("stage")
    staging.add_argument("--bundle", type=Path, required=True)
    staging.add_argument("--sha256", required=True)
    upgrading = commands.add_parser("upgrade")
    upgrading.add_argument("--bundle", type=Path, required=True)
    upgrading.add_argument("--sha256", required=True)
    commands.add_parser("activate")
    removal = commands.add_parser("remove")
    removal.add_argument("--purge-stage", action="store_true")
    args = parser.parse_args()
    if args.command == "stage":
        stage(args.home, args.bundle, args.sha256)
    elif args.command == "upgrade":
        upgrade(args.home, args.bundle, args.sha256)
    elif args.command == "activate":
        activate(args.home)
    else:
        remove(args.home, purge_stage=args.purge_stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
