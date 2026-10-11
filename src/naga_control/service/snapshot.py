"""Qt-free service snapshots with separate desired and observed hardware state."""

from naga_control.domain.hardware import DeviceMode, HardwareState, SettingsFailure
from naga_control.domain.profiles import Configuration


def snapshot_document(
    state: HardwareState | None,
    configuration: Configuration | None,
    failures: tuple[SettingsFailure, ...],
    calibrating: bool,
    observed_mode: DeviceMode | None,
    mode_error: str | None,
    remapping_active: bool,
) -> dict[str, object]:
    mode_ready = (
        state is not None
        and state.status == "available"
        and configuration is not None
        and observed_mode == configuration.mode
        and (not configuration.remapping_enabled or observed_mode == "firmware" or remapping_active)
    )
    status = state.status if state is not None else "absent"
    if (
        status == "available"
        and configuration is not None
        and configuration.hardware_writes
        and not mode_ready
    ):
        status = "unavailable"
    return {
        "status": status,
        "generation": state.generation if state is not None else 0,
        "transport": state.transport if state is not None else None,
        "error": state.error.message if state is not None and state.error is not None else None,
        "settings_failures": [f"{failure.setting}: {failure.message}" for failure in failures],
        "calibrating": calibrating,
        "desired_mode": configuration.mode if configuration is not None else None,
        "observed_mode": observed_mode,
        "mode_ready": mode_ready,
        "mode_error": mode_error,
        "hardware_writes_enabled": (
            configuration.hardware_writes if configuration is not None else False
        ),
        "remapping_enabled": (
            configuration.remapping_enabled if configuration is not None else False
        ),
        "remapping_active": remapping_active,
        "lighting_writes_enabled": (
            configuration.profile(configuration.active_profile).lighting_writes
            if configuration is not None
            else False
        ),
        "observation_sources": {
            "dpi": "openrazer-device-read",
            "dpi_stages": "openrazer-device-read",
            "scroll": "openrazer-device-read",
            "power": "openrazer-device-read",
            "poll_rate": "openrazer-daemon-cache",
            "lighting": "not-read",
        },
        "observed": observed_hardware(state),
    }


def observed_hardware(state: HardwareState | None) -> dict[str, object]:
    if state is None or state.status != "available":
        return {}
    dpi = state.dpi
    return {
        "dpi": (dpi.x, dpi.y) if dpi is not None else None,
        "dpi_stage_count": len(state.dpi_stages),
        "active_dpi_stage": state.active_dpi_stage,
        "max_dpi": state.max_dpi,
        "scroll_mode": state.scroll_mode,
        "scroll_mode_options": list(state.scroll_mode_options),
        "scroll_acceleration": state.scroll_acceleration,
        "scroll_smart_reel": state.scroll_smart_reel,
        "poll_rate": state.poll_rate,
        "poll_rate_verified": state.poll_rate_verified,
        "idle_seconds": state.idle_seconds,
        "low_battery_threshold": state.low_battery_threshold,
        "battery_percent": state.battery_percent,
        "charging": state.charging,
        "firmware_version": state.firmware_version,
    }
