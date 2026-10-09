import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.build_hugin_bundle import build
from scripts.owned_install import STATE_RELATIVE, activate, remove, stage


def _bundle(tmp_path: Path) -> tuple[Path, str]:
    appdir = tmp_path / "input" / "arbitrary-build-directory"
    files = {
        "AppRun": "#!/bin/sh\nexit 0\n",
        "usr/share/naga-control/system/systemd/user/naga-control.service": "[Service]\n",
        "usr/share/naga-control/system/dbus-1/services/org.nagacontrol.Service1.service": (
            "[D-BUS Service]\nName=org.nagacontrol.Service1\n"
        ),
        "usr/share/naga-control/system/desktop/org.nagacontrol.NagaControl.desktop": (
            "[Desktop Entry]\nType=Application\n"
        ),
    }
    for relative, contents in files.items():
        path = appdir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    bundle = tmp_path / "naga-control-hugin.tar.xz"
    metadata = build(appdir, bundle)
    return bundle, str(metadata["sha256"])


def test_stage_is_hash_verified_and_has_no_active_integration(tmp_path: Path) -> None:
    bundle, expected = _bundle(tmp_path)
    home = tmp_path / "home"
    home.mkdir()

    appdir = stage(home, bundle, expected)

    assert (appdir / "AppRun").is_file()
    assert not (home / ".config/systemd/user/naga-control.service").exists()
    assert not (home / ".local/share/dbus-1/services/org.nagacontrol.Service1.service").exists()
    state = json.loads((home / STATE_RELATIVE).read_text(encoding="utf-8"))
    assert state["bundle_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert state["active_files"] == {}


def test_stage_rejects_a_wrong_hash_without_leaving_state(tmp_path: Path) -> None:
    bundle, _expected = _bundle(tmp_path)
    home = tmp_path / "home"
    home.mkdir()

    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        stage(home, bundle, "0" * 64)

    assert not (home / STATE_RELATIVE).exists()


def test_activation_failure_rolls_back_integration_and_never_enables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, expected = _bundle(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    stage(home, bundle, expected)
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "start" in command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        activate(home)

    assert not (home / ".config/systemd/user/naga-control.service").exists()
    assert not any("enable" in command for command in calls)
    state = json.loads((home / STATE_RELATIVE).read_text(encoding="utf-8"))
    assert state["active_files"] == {}


def test_activation_refuses_write_enabled_profile_before_installing_files(tmp_path: Path) -> None:
    bundle, expected = _bundle(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    stage(home, bundle, expected)
    config = home / ".config/naga-control/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("hardware_writes = true\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="hardware_writes = false"):
        activate(home)

    assert not (home / ".local/bin/naga-control").exists()


def test_remove_preserves_profiles_and_can_purge_only_owned_stage(tmp_path: Path) -> None:
    bundle, expected = _bundle(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    appdir = stage(home, bundle, expected)
    profile = home / ".config/naga-control/config.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("hardware_writes = false\n", encoding="utf-8")

    remove(home, purge_stage=True)

    assert profile.read_text(encoding="utf-8") == "hardware_writes = false\n"
    assert not appdir.exists()
    assert not (home / STATE_RELATIVE).exists()


def test_successful_activation_and_removal_touch_only_manifested_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, expected = _bundle(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    appdir = stage(home, bundle, expected)
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        status = 3 if "is-active" in command else 0
        return subprocess.CompletedProcess(command, status)

    monkeypatch.setattr(subprocess, "run", run)
    activate(home)
    state = json.loads((home / STATE_RELATIVE).read_text(encoding="utf-8"))
    active_files = tuple(Path(name) for name in state["active_files"])

    assert len(active_files) == 5
    assert all(path.is_file() for path in active_files)
    assert not any("enable" in command for command in calls)

    remove(home)

    assert all(not path.exists() for path in active_files)
    assert appdir.is_dir()
    state = json.loads((home / STATE_RELATIVE).read_text(encoding="utf-8"))
    assert state["active_files"] == {}


def test_remove_preserves_a_modified_owned_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, expected = _bundle(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    stage(home, bundle, expected)

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    activate(home)
    wrapper = home / ".local/bin/naga-control"
    wrapper.write_text("locally modified\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="modified; preserving"):
        remove(home)

    assert wrapper.read_text(encoding="utf-8") == "locally modified\n"


def test_remove_refuses_while_the_service_is_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, expected = _bundle(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    stage(home, bundle, expected)

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    activate(home)

    with pytest.raises(RuntimeError, match="service is active"):
        remove(home)

    assert (home / ".config/systemd/user/naga-control.service").is_file()
