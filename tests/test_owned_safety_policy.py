from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from service_runtime_fakes import Session, Worker, available, connection
from test_openrazer_backend import FakeDevice
from test_openrazer_settings import FakeClient

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.adapters.openrazer.capabilities import read_hardware_state
from naga_control.adapters.openrazer.settings import apply_steps
from naga_control.config import dump_toml, parse_toml
from naga_control.domain.actions import KeyAction, KeyComboAction
from naga_control.domain.defaults import default_configuration
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.hardware import HardwareState
from naga_control.domain.profiles import Configuration
from naga_control.service.calibration import adopt_observed_settings
from naga_control.service.runtime import NagaService


async def test_default_start_is_read_only_and_does_not_grab_or_correct_mode() -> None:
    worker = Worker()
    worker.mode = "firmware"
    sessions: list[Session] = []

    def factory(_connection: NagaConnection, _configuration: Configuration) -> Session:
        session = Session()
        sessions.append(session)
        return session

    service = NagaService(
        lambda: (connection(),),
        lambda: None,
        worker,
        factory,
    )

    state = await service.start()

    assert state.status == "available"
    assert worker.events == ["start", "rescan:1", "read_mode"]
    assert sessions == []
    assert service.snapshot()["status"] == "available"
    assert service.snapshot()["hardware_writes_enabled"] is False
    assert service.snapshot()["remapping_enabled"] is False
    assert service.snapshot()["remapping_active"] is False
    await service.stop()


async def test_activation_refuses_an_incomplete_hardware_snapshot() -> None:
    worker = Worker()
    service = NagaService(lambda: (connection(),), lambda: None, worker, _session)
    await service.start()
    requested = replace(default_configuration(), revision=1, hardware_writes=True)

    with pytest.raises(RuntimeError, match="complete device-verified"):
        await service.apply_configuration(0, dump_toml(requested))

    assert "settings" not in worker.events
    assert not any(event.startswith("set_mode:") for event in worker.events)
    await service.stop()


async def test_activation_accepts_only_after_all_write_targets_are_observed() -> None:
    complete = _complete_state()
    worker = Worker()
    worker.rescan_state = complete
    service = NagaService(lambda: (connection(),), lambda: None, worker, _session)
    await service.start()
    adopted = adopt_observed_settings(default_configuration(), complete)
    assert adopted is not None
    requested = replace(adopted, hardware_writes=True)

    assert await service.apply_configuration(0, dump_toml(requested)) == 1
    assert worker.events.count("settings") == 1
    await service.stop()


async def test_activation_refuses_daemon_cached_poll_rate() -> None:
    complete_except_poll_verification = replace(_complete_state(), poll_rate_verified=False)
    worker = Worker()
    worker.rescan_state = complete_except_poll_verification
    service = NagaService(lambda: (connection(),), lambda: None, worker, _session)
    await service.start()
    adopted = adopt_observed_settings(default_configuration(), complete_except_poll_verification)
    assert adopted is not None

    with pytest.raises(RuntimeError, match="complete device-verified"):
        await service.apply_configuration(0, dump_toml(replace(adopted, hardware_writes=True)))

    assert "settings" not in worker.events
    await service.stop()


async def test_activation_refuses_stored_settings_that_do_not_match_observation() -> None:
    complete = _complete_state()
    worker = Worker()
    worker.rescan_state = complete
    service = NagaService(lambda: (connection(),), lambda: None, worker, _session)
    await service.start()
    requested = replace(default_configuration(), revision=1, hardware_writes=True)

    with pytest.raises(RuntimeError, match="desired settings to match observed hardware"):
        await service.apply_configuration(0, dump_toml(requested))

    assert "settings" not in worker.events
    await service.stop()


async def test_first_activation_refuses_lighting_writes() -> None:
    complete = _complete_state()
    worker = Worker()
    worker.rescan_state = complete
    service = NagaService(lambda: (connection(),), lambda: None, worker, _session)
    await service.start()
    adopted = adopt_observed_settings(default_configuration(), complete)
    assert adopted is not None
    profile = replace(adopted.profile("default"), lighting_writes=True)
    requested = replace(adopted, hardware_writes=True, profiles=(("default", profile),))

    with pytest.raises(RuntimeError, match="lighting writes to remain disabled"):
        await service.apply_configuration(0, dump_toml(requested))

    assert "settings" not in worker.events
    await service.stop()


def test_configuration_round_trip_keeps_both_write_gates_default_off() -> None:
    configuration = parse_toml(dump_toml(default_configuration()))

    assert configuration.hardware_writes is False
    assert configuration.remapping_enabled is False
    assert configuration.profile("default").lighting_writes is False


async def test_remapping_only_starts_input_without_hardware_setting_writes() -> None:
    worker = Worker()
    sessions: list[Session] = []
    configuration = replace(default_configuration(), remapping_enabled=True)

    def factory(_connection: NagaConnection, _configuration: Configuration) -> Session:
        session = Session()
        sessions.append(session)
        return session

    service = NagaService(lambda: (connection(),), lambda: configuration, worker, factory)

    await service.start()

    assert worker.events == ["start", "rescan:1", "read_mode"]
    assert [session.events for session in sessions] == [["start"]]
    assert service.snapshot()["hardware_writes_enabled"] is False
    assert service.snapshot()["remapping_enabled"] is True
    assert service.snapshot()["remapping_active"] is True
    await service.stop()


def test_power_reads_are_captured_for_the_activation_gate() -> None:
    class PowerDevice(FakeDevice):
        def get_idle_time(self) -> int:
            return 600

        def get_low_battery_threshold(self) -> int:
            return 15

    state = read_hardware_state(PowerDevice(), 1, "hyperspeed")

    assert (state.idle_seconds, state.low_battery_threshold) == (600, 15)


def test_lighting_is_not_written_without_the_independent_opt_in() -> None:
    client = FakeClient()

    assert apply_steps(client, default_configuration().profile("default")) == ()
    assert not any(call.startswith(("grid:", "logo:", "scroll:")) for call in client.calls)


@pytest.mark.parametrize(
    "action", [lambda: KeyAction("f13"), lambda: KeyComboAction(("left_ctrl",), "f13")]
)
def test_f13_is_reserved_from_naga_generated_output(action: Callable[[], object]) -> None:
    with pytest.raises(ConfigValidationError, match="physical-keyboard PTT isolation"):
        action()


def test_udev_rule_grants_only_naga_inputs_and_uinput() -> None:
    rule = (
        Path(__file__).parents[1] / "system/udev/70-naga-control.rules"
    ).read_text(encoding="utf-8")

    assert rule.count('TAG+="uaccess"') == 3
    assert 'ATTRS{idProduct}=="00e7"' in rule
    assert 'ATTRS{idProduct}=="00e8"' in rule
    assert 'KERNEL=="uinput"' in rule
    assert 'ATTRS{name}' not in rule
    assert "046d" not in rule.lower()


def _session(_connection: NagaConnection, _configuration: Configuration) -> Session:
    return Session()


def _complete_state() -> HardwareState:
    return replace(
        available(),
        poll_rate=1000,
        poll_rate_verified=True,
        idle_seconds=300,
        low_battery_threshold=20,
    )


def test_unavailable_state_does_not_retain_new_optional_power_values() -> None:
    with pytest.raises(ValueError, match="unavailable hardware states"):
        HardwareState("unavailable", 1, idle_seconds=600)
