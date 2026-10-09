"""Pure safety gates for the explicit transition out of discovery mode."""

from naga_control.domain.hardware import DeviceMode, HardwareState
from naga_control.domain.profiles import Configuration


def hardware_state_is_complete(state: HardwareState | None) -> bool:
    """Require a readable value for every non-lighting setting before writes."""
    return (
        state is not None
        and state.status == "available"
        and bool(state.dpi_stages)
        and state.scroll_mode is not None
        and state.scroll_acceleration is not None
        and state.scroll_smart_reel is not None
        and state.poll_rate in {125, 500, 1000}
        and state.poll_rate_verified
        and state.idle_seconds is not None
        and state.low_battery_threshold is not None
    )


def desired_state_matches_observation(
    configuration: Configuration, state: HardwareState | None
) -> bool:
    """Confirm activation cannot turn stored defaults into hardware changes."""
    if not hardware_state_is_complete(state) or state is None:
        return False
    profile = configuration.profile(configuration.active_profile)
    desired_stages = tuple((stage.x, stage.y) for stage in profile.dpi.stages)
    observed_stages = tuple((stage.x, stage.y) for stage in state.dpi_stages)
    selected = profile.dpi.stages[profile.dpi.active_stage - 1]
    return (
        desired_stages == observed_stages
        and profile.dpi.active_stage == state.active_dpi_stage
        and state.dpi is not None
        and (selected.x, selected.y) == (state.dpi.x, state.dpi.y)
        and profile.scroll.mode == state.scroll_mode
        and profile.scroll.acceleration == state.scroll_acceleration
        and profile.scroll.smart_reel == state.scroll_smart_reel
        and profile.poll_rate == state.poll_rate
        and profile.power.idle_seconds == state.idle_seconds
        and profile.power.low_battery_threshold == state.low_battery_threshold
    )


def validate_first_activation(
    current: Configuration,
    requested: Configuration,
    state: HardwareState | None,
    observed_mode: DeviceMode | None,
) -> None:
    """Refuse the first write-capable transition unless it is a no-op."""
    if not requested.hardware_writes or current.hardware_writes:
        return
    profile = requested.profile(requested.active_profile)
    if profile.lighting_writes:
        raise RuntimeError("first activation requires lighting writes to remain disabled")
    if not hardware_state_is_complete(state):
        raise RuntimeError(
            "hardware writes require complete device-verified DPI, scroll, polling, and power discovery"
        )
    if requested.mode != observed_mode:
        raise RuntimeError("first activation requires desired device mode to match observed mode")
    if not desired_state_matches_observation(requested, state):
        raise RuntimeError("first activation requires desired settings to match observed hardware")
