"""4-noks Elios4You integration.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

from dataclasses import dataclass
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    CONF_ENABLE_REPAIR_NOTIFICATION,
    CONF_FAILURES_THRESHOLD,
    CONF_NAME,
    CONF_POWER_REDUCER,
    CONF_RECOVERY_SCRIPT,
    CONF_SCAN_INTERVAL,
    DEFAULT_ENABLE_REPAIR_NOTIFICATION,
    DEFAULT_FAILURES_THRESHOLD,
    DEFAULT_RECOVERY_SCRIPT,
    DOMAIN,
    PR_ENTITY_KEYS,
    STARTUP_MESSAGE,
)
from .coordinator import Elios4YouCoordinator
from .frontend import async_register_frontend, async_register_websocket
from .helpers import log_debug, log_error, log_info

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

_DAY_NAMES = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")

# The type alias needs to be suffixed with 'ConfigEntry'
type Elios4YouConfigEntry = ConfigEntry[RuntimeData]


@dataclass
class RuntimeData:
    """Class to hold your data."""

    coordinator: Elios4YouCoordinator


# Module-level set of hass instance IDs for which frontend resources have been registered.
# Never cleaned up on unload because the static HTTP path persists for the HA session.
_FRONTEND_SETUP_COMPLETE: set[int] = set()


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register domain-level services once when the integration is first loaded."""
    _register_schedule_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: Elios4YouConfigEntry) -> bool:
    """Set up this integration using UI."""
    log_info(_LOGGER, "async_setup_entry", STARTUP_MESSAGE)
    log_debug(_LOGGER, "async_setup_entry", "Setup config_entry", domain=DOMAIN)

    # ── Frontend registration (runs once per HA session, not per config entry) ──
    # Guarded by a module-level set so multiple config entries and config-entry
    # reloads do not attempt to re-register the already-permanent static path.
    if id(hass) not in _FRONTEND_SETUP_COMPLETE:
        _FRONTEND_SETUP_COMPLETE.add(id(hass))
        async_register_websocket(hass)

        async def _setup_frontend(_event=None) -> None:
            await async_register_frontend(hass)

        if hass.state == CoreState.running:
            await _setup_frontend()
        else:
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _setup_frontend)

    # Initialise the coordinator that manages data updates from the API
    coordinator = Elios4YouCoordinator(hass, config_entry)

    # If the refresh fails, async_config_entry_first_refresh() will
    # raise ConfigEntryNotReady and setup will try again later
    # ref.: https://developers.home-assistant.io/docs/integration_setup_failures
    await coordinator.async_config_entry_first_refresh()

    # Test to see if api initialised correctly, else raise ConfigNotReady to make HA retry setup
    if not coordinator.api.data["sn"]:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connection_timeout",
            translation_placeholders={"device_name": str(config_entry.data.get(CONF_NAME, ""))},
        )

    # Store coordinator in runtime_data to make it accessible throughout the integration
    config_entry.runtime_data = RuntimeData(coordinator)

    # Note: No manual update listener needed - OptionsFlowWithReload handles reload automatically

    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # Register device
    async_update_device_registry(hass, config_entry)

    # Apply Power Reducer entity enabled/disabled state based on the option.
    # Deferred via async_create_task so the entity platform has settled before the registry
    # change fires (entities created with enabled_default=False start as INTEGRATION-disabled).
    async def _deferred_pr_state() -> None:
        _async_apply_pr_entity_state(hass, config_entry)

    hass.async_create_task(_deferred_pr_state(), eager_start=False)

    # Return true to denote a successful setup
    return True


@callback
def _async_apply_pr_entity_state(
    hass: HomeAssistant, config_entry: Elios4YouConfigEntry
) -> None:
    """Enable or disable Power Reducer entities in the entity registry.

    Only acts when the option has been explicitly set (not None).
    - power_reducer=True  → enables entities disabled by the integration
    - power_reducer=False → disables entities that are currently enabled
    This allows existing config entries (where the option is not yet set) to be unaffected
    until the user opens the options dialog and explicitly saves a choice.
    """
    option_value: bool | None = config_entry.options.get(CONF_POWER_REDUCER)
    if option_value is None:
        # Option not yet saved by the user — leave entity states untouched.
        log_debug(
            _LOGGER,
            "_async_apply_pr_entity_state",
            "Power Reducer option not set; skipping entity registry update",
        )
        return

    ent_reg = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(ent_reg, config_entry.entry_id):
        if not any(entry.unique_id.endswith(f"_{key}") for key in PR_ENTITY_KEYS):
            continue
        if option_value:
            # Enable entities that were disabled by the integration (not by the user).
            if entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                ent_reg.async_update_entity(entry.entity_id, disabled_by=None)
        else:
            # Disable entities that are currently enabled.
            if entry.disabled_by is None:
                ent_reg.async_update_entity(
                    entry.entity_id,
                    disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                )

    log_debug(
        _LOGGER,
        "_async_apply_pr_entity_state",
        "Power Reducer entity states applied",
        power_reducer=option_value,
    )


@callback
def async_update_device_registry(hass: HomeAssistant, config_entry: Elios4YouConfigEntry) -> None:
    """Manual device registration."""
    coordinator = config_entry.runtime_data.coordinator
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        hw_version=str(coordinator.api.data.get("hwver", "")),
        identifiers={(DOMAIN, str(coordinator.api.data.get("sn", "")))},
        manufacturer=str(coordinator.api.data.get("manufact", "")),
        model=str(coordinator.api.data.get("model", "")),
        name=config_entry.data.get(CONF_NAME),
        serial_number=str(coordinator.api.data.get("sn", "")),
        sw_version=str(coordinator.api.data.get("swver", "")),
        configuration_url=None,
        via_device=None,
    )

    # Store device_id in coordinator for device triggers
    serial_number = str(coordinator.api.data.get("sn", ""))
    device = device_registry.async_get_device(identifiers={(DOMAIN, serial_number)})
    if device:
        coordinator.device_id = device.id
        log_debug(
            _LOGGER,
            "async_update_device_registry",
            "Device ID stored in coordinator",
            device_id=device.id,
        )


def _register_schedule_services(hass: HomeAssistant) -> None:
    """Register Power Reducer scheduler services (called once, shared across all entries)."""

    def _get_coordinator(entry_id: str) -> Elios4YouCoordinator:
        """Resolve a coordinator from a config entry ID, raising ServiceValidationError if invalid."""
        config_entry = hass.config_entries.async_get_entry(entry_id)
        if config_entry is None or config_entry.domain != DOMAIN:
            raise ServiceValidationError("Invalid or missing config_entry_id for this integration")
        runtime_data = getattr(config_entry, "runtime_data", None)
        if runtime_data is None:
            raise ServiceValidationError("Integration instance is not yet fully initialized")
        return runtime_data.coordinator

    def _slot_to_time(index: int) -> str:
        """Convert 0-based 30-min slot index to 'HH:MM' string."""
        minutes = index * 30
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _time_to_slot(time_str: str) -> int:
        """Convert 'HH:MM' or 'HH:MM:SS' to 0-based 30-min slot index. Raises ValueError if invalid."""
        parts = time_str.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(f"Invalid time format: {time_str!r}")
        hours, mins = int(parts[0]), int(parts[1])
        if not 0 <= hours <= 23:
            raise ValueError(f"Hour must be 0-23, got: {hours!r}")
        if mins not in (0, 30):
            raise ValueError(f"Time must be on a 30-min boundary, got: {time_str!r}")
        return hours * 2 + mins // 30

    async def _handle_get_schedule(call: ServiceCall) -> dict:
        """Return the Power Reducer schedule for a day as structured data."""
        coordinator = _get_coordinator(call.data["config_entry_id"])
        day = int(call.data["day"])
        if not 0 <= day <= 6:
            raise ServiceValidationError(f"Day must be 0-6, got {day}")
        slots_raw = await coordinator.api.async_read_schedule(day)
        if slots_raw is None:
            raise ServiceValidationError(f"Failed to read schedule for day {day} from device")
        return {
            "day": _DAY_NAMES[day],
            "slots": [{"time": _slot_to_time(i), "mode": mode} for i, mode in enumerate(slots_raw)],
        }

    async def _handle_set_schedule(call: ServiceCall) -> None:
        """Write the full Power Reducer schedule for a day."""
        coordinator = _get_coordinator(call.data["config_entry_id"])
        day = int(call.data["day"])
        if not 0 <= day <= 6:
            raise ServiceValidationError(f"Day must be 0-6, got {day}")
        slots: list[str] = list(call.data["slots"])
        if len(slots) != 48:
            raise ServiceValidationError(f"Expected 48 slots, got {len(slots)}")
        valid_modes = {"off", "auto", "boost"}
        invalid = [s for s in slots if s.lower() not in valid_modes]
        if invalid:
            raise ServiceValidationError(
                f"Invalid slot modes: {invalid!r}. Allowed: off, auto, boost"
            )
        success = await coordinator.api.async_write_schedule(day, slots)
        if not success:
            raise ServiceValidationError(f"Failed to write schedule for day {day} to device")

    async def _handle_set_schedule_range(call: ServiceCall) -> None:
        """Set a time range in the schedule to a specific mode."""
        coordinator = _get_coordinator(call.data["config_entry_id"])
        day = int(call.data["day"])
        if not 0 <= day <= 6:
            raise ServiceValidationError(f"Day must be 0-6, got {day}")
        mode = str(call.data["mode"]).lower()
        if mode not in {"off", "auto", "boost"}:
            raise ServiceValidationError(f"Invalid mode {mode!r}. Allowed: off, auto, boost")
        try:
            start_slot = _time_to_slot(str(call.data["start_time"]))
            end_slot = _time_to_slot(str(call.data["end_time"]))
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        if start_slot >= end_slot:
            raise ServiceValidationError(
                f"start_time must be before end_time (got slots {start_slot} >= {end_slot})"
            )
        # Read current schedule, patch the range, write back
        current = await coordinator.api.async_read_schedule(day)
        if current is None:
            raise ServiceValidationError(f"Failed to read current schedule for day {day}")
        for i in range(start_slot, end_slot):
            current[i] = mode
        success = await coordinator.api.async_write_schedule(day, current)
        if not success:
            raise ServiceValidationError(
                f"Failed to write updated schedule for day {day} to device"
            )

    _get_schedule_schema = vol.Schema(
        {
            vol.Required("config_entry_id"): str,
            vol.Required("day"): vol.All(vol.Coerce(int), vol.Range(min=0, max=6)),
        }
    )
    _set_schedule_schema = vol.Schema(
        {
            vol.Required("config_entry_id"): str,
            vol.Required("day"): vol.All(vol.Coerce(int), vol.Range(min=0, max=6)),
            vol.Required("slots"): vol.All(
                list,
                vol.Length(min=48, max=48),
                [vol.In(["off", "auto", "boost"])],
            ),
        }
    )
    _set_schedule_range_schema = vol.Schema(
        {
            vol.Required("config_entry_id"): str,
            vol.Required("day"): vol.All(vol.Coerce(int), vol.Range(min=0, max=6)),
            vol.Required("start_time"): str,
            vol.Required("end_time"): str,
            vol.Required("mode"): vol.In(["off", "auto", "boost"]),
        }
    )

    hass.services.async_register(
        DOMAIN,
        "get_schedule",
        _handle_get_schedule,
        schema=_get_schedule_schema,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "set_schedule", _handle_set_schedule, schema=_set_schedule_schema
    )
    hass.services.async_register(
        DOMAIN,
        "set_schedule_range",
        _handle_set_schedule_range,
        schema=_set_schedule_range_schema,
    )
    log_debug(_LOGGER, "_register_schedule_services", "Scheduler services registered")


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Delete device if not entities."""
    # identifiers is a set of tuples like {("domain", "id")} - check if any tuple has DOMAIN
    if any(identifier[0] == DOMAIN for identifier in device_entry.identifiers):
        log_error(
            _LOGGER,
            "async_remove_config_entry_device",
            "You cannot delete the device using device delete. Remove the integration instead.",
        )
        return False
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: Elios4YouConfigEntry) -> bool:
    """Unload a config entry."""
    log_debug(_LOGGER, "async_unload_entry", "Unload config_entry: started")

    # Unload platforms - only cleanup runtime_data if successful
    # ref.: https://developers.home-assistant.io/blog/2025/02/19/new-config-entry-states/
    if unload_ok := await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS):
        log_debug(_LOGGER, "async_unload_entry", "Platforms unloaded successfully")
        # Cleanup per-entry resources only if unload succeeded
        await config_entry.runtime_data.coordinator.api.close()
        log_debug(_LOGGER, "async_unload_entry", "Closed API connection")
    else:
        log_debug(_LOGGER, "async_unload_entry", "Platform unload failed, skipping cleanup")

    log_debug(
        _LOGGER,
        "async_unload_entry",
        "Unload config_entry: completed",
        unload_ok=unload_ok,
    )
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries.

    This function handles migration of config entries when the schema version changes.
    """
    current_version = 3

    # Handle downgrade scenario (per HA best practice)
    if config_entry.version > current_version:
        log_error(
            _LOGGER,
            "async_migrate_entry",
            "Cannot downgrade from future version",
            from_version=config_entry.version,
            current_version=current_version,
        )
        return False

    log_info(
        _LOGGER,
        "async_migrate_entry",
        "Starting migration",
        from_version=config_entry.version,
        target_version=current_version,
    )

    if config_entry.version == 1:
        # Migrate from v1 to v2: move scan_interval from data to options
        new_data = {**config_entry.data}
        new_options = {**config_entry.options}

        # Move scan_interval to options if present in data
        if CONF_SCAN_INTERVAL in new_data:
            new_options[CONF_SCAN_INTERVAL] = new_data.pop(CONF_SCAN_INTERVAL)

        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options=new_options,
            version=2,
        )
        log_info(_LOGGER, "async_migrate_entry", "Migration to version 2 complete")

    if config_entry.version == 2:
        # Migrate from v2 to v3: add new repair notification options with defaults
        new_options = {**config_entry.options}

        # Add new options with defaults if not present
        if CONF_ENABLE_REPAIR_NOTIFICATION not in new_options:
            new_options[CONF_ENABLE_REPAIR_NOTIFICATION] = DEFAULT_ENABLE_REPAIR_NOTIFICATION
        if CONF_FAILURES_THRESHOLD not in new_options:
            new_options[CONF_FAILURES_THRESHOLD] = DEFAULT_FAILURES_THRESHOLD
        if CONF_RECOVERY_SCRIPT not in new_options:
            new_options[CONF_RECOVERY_SCRIPT] = DEFAULT_RECOVERY_SCRIPT

        hass.config_entries.async_update_entry(
            config_entry,
            options=new_options,
            version=3,
        )
        log_info(_LOGGER, "async_migrate_entry", "Migration to version 3 complete")

    return True
