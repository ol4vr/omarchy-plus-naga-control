import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.build_hugin_bundle import build
from scripts.owned_install import STATE_RELATIVE, activate, remove, stage, upgrade


def test_desktop_entry_uses_installer_owned_launcher() -> None:
    desktop = (
        Path(__file__).parents[1] / "system/desktop/org.nagacontrol.NagaControl.desktop"
    ).read_text(encoding="utf-8")

    assert [line for line in desktop.splitlines() if line.startswith("Exec=")] == [
        "Exec=naga-control"
    ]


def _bundle(tmp_path: Path, marker: str = "current") -> tuple[Path, str]:
    appdir = tmp_path / f"input-{marker}" / "arbitrary-build-directory"
    files = {
        "AppRun": f"#!/bin/sh\n# {marker}\nexit 0\n",
        "usr/share/naga-control/system/systemd/user/naga-control.service": (
            f"[Service]\n# {marker}\n"
        ),
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
    bundle = tmp_path / f"naga-control-hugin-{marker}.tar.xz"
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


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("hardware_writes = true\n", "hardware_writes = false"),
        ("remapping_enabled = true\n", "remapping_enabled = false"),
        (
            "[profiles.default]\nlighting_writes = true\n",
            "profiles.default.lighting_writes = false",
        ),
    ],
)
def test_activation_refuses_enabled_write_or_remapping_policy_before_installing_files(
    tmp_path: Path, document: str, message: str
) -> None:
    bundle, expected = _bundle(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    stage(home, bundle, expected)
    config = home / ".config/naga-control/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(document, encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
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


def test_upgrade_restarts_active_service_and_preserves_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_bundle, old_hash = _bundle(tmp_path, "old")
    new_bundle, new_hash = _bundle(tmp_path, "new")
    home = tmp_path / "home"
    home.mkdir()
    old_appdir = stage(home, old_bundle, old_hash)
    config = home / ".config/naga-control/config.toml"
    config.parent.mkdir(parents=True)
    document = "hardware_writes = false\nremapping_enabled = false\n"
    config.write_text(document, encoding="utf-8")
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    activate(home)
    calls.clear()

    new_appdir = upgrade(home, new_bundle, new_hash)

    assert calls == [
        ["systemctl", "--user", "is-active", "--quiet", "naga-control.service"],
        ["systemctl", "--user", "stop", "naga-control.service"],
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "start", "naga-control.service"],
        ["systemctl", "--user", "is-active", "--quiet", "naga-control.service"],
    ]
    assert config.read_text(encoding="utf-8") == document
    assert new_appdir.is_dir()
    assert not old_appdir.exists()
    assert str(new_appdir) in (home / ".local/bin/naga-control").read_text(encoding="utf-8")
    state = json.loads((home / STATE_RELATIVE).read_text(encoding="utf-8"))
    assert state["bundle_sha256"] == new_hash
    assert state["appdir"] == str(new_appdir)


def test_failed_upgrade_restores_and_restarts_previous_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_bundle, old_hash = _bundle(tmp_path, "old")
    new_bundle, new_hash = _bundle(tmp_path, "new")
    home = tmp_path / "home"
    home.mkdir()
    old_appdir = stage(home, old_bundle, old_hash)
    calls: list[list[str]] = []
    fail_new_start = False

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal fail_new_start
        calls.append(command)
        if command[-2:] == ["start", "naga-control.service"] and fail_new_start:
            fail_new_start = False
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    activate(home)
    previous_wrapper = (home / ".local/bin/naga-control").read_bytes()
    calls.clear()
    fail_new_start = True

    with pytest.raises(subprocess.CalledProcessError):
        upgrade(home, new_bundle, new_hash)

    assert calls[-4:] == [
        ["systemctl", "--user", "stop", "naga-control.service"],
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "start", "naga-control.service"],
        ["systemctl", "--user", "is-active", "--quiet", "naga-control.service"],
    ]
    assert (home / ".local/bin/naga-control").read_bytes() == previous_wrapper
    assert old_appdir.is_dir()
    assert not (home / ".local/opt/naga-control" / new_hash).exists()
    state = json.loads((home / STATE_RELATIVE).read_text(encoding="utf-8"))
    assert state["bundle_sha256"] == old_hash
    assert state["appdir"] == str(old_appdir)


def test_upgrade_of_inactive_stage_avoids_systemd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_bundle, old_hash = _bundle(tmp_path, "old")
    new_bundle, new_hash = _bundle(tmp_path, "new")
    home = tmp_path / "home"
    home.mkdir()
    stage(home, old_bundle, old_hash)

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"unexpected systemctl call: {command}")

    monkeypatch.setattr(subprocess, "run", run)
    new_appdir = upgrade(home, new_bundle, new_hash)

    assert new_appdir.is_dir()
    state = json.loads((home / STATE_RELATIVE).read_text(encoding="utf-8"))
    assert state["active_files"] == {}


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("hardware_writes = true\n", "hardware_writes = false"),
        ("remapping_enabled = true\n", "remapping_enabled = false"),
        (
            "[profiles.default]\nlighting_writes = true\n",
            "profiles.default.lighting_writes = false",
        ),
    ],
)
def test_upgrade_refuses_enabled_write_or_remapping_policy(
    tmp_path: Path, document: str, message: str
) -> None:
    old_bundle, old_hash = _bundle(tmp_path, "old")
    new_bundle, new_hash = _bundle(tmp_path, "new")
    home = tmp_path / "home"
    home.mkdir()
    old_appdir = stage(home, old_bundle, old_hash)
    config = home / ".config/naga-control/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(document, encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        upgrade(home, new_bundle, new_hash)

    assert old_appdir.is_dir()
    assert not (home / ".local/opt/naga-control" / new_hash).exists()
