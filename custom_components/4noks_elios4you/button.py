"""Button Platform for 4-noks Elios4You Power Reducer controls.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

import asyncio
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Elios4YouConfigEntry
from .const import BUTTON_ENTITIES, DEFAULT_BOOST_DURATION, DEFAULT_BOOST_LEVEL, DOMAIN
from .coordinator import Elios4YouCoordinator
from .helpers import log_debug, log_warning

# Maintenance/refresh buttons go into DIAGNOSTIC; operational action buttons have no category.
_DIAGNOSTIC_ACTIONS = {"refresh_pr_params", "sync_clock"}

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: Elios4YouConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Button Platform setup."""
    coordinator = config_entry.runtime_data.coordinator
    buttons = [Elios4YouButton(coordinator, entity_def) for entity_def in BUTTON_ENTITIES]
    async_add_entities(buttons)


class Elios4YouButton(CoordinatorEntity[Elios4YouCoordinator], ButtonEntity):
    """Button entity for Power Reducer controls."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Elios4YouCoordinator,
        entity_def: dict[str, Any],
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._key: str = entity_def["key"]
        self._action: str = entity_def["action"]
        self._attr_translation_key = self._key
        self._attr_icon = entity_def["icon"]
        self._attr_entity_category = (
            EntityCategory.DIAGNOSTIC if self._action in _DIAGNOSTIC_ACTIONS else None
        )
        self._attr_entity_registry_enabled_default = entity_def.get("enabled_default", False)
        self._device_sn: str = str(coordinator.api.data.get("sn", ""))
        self._device_name: str = str(coordinator.api.name)
        self._device_model: str = str(coordinator.api.data.get("model", ""))
        self._device_manufact: str = str(coordinator.api.data.get("manufact", ""))
        self._device_hwver: str = str(coordinator.api.data.get("hwver", ""))
        self._device_swver: str = str(coordinator.api.data.get("swver", ""))
        log_debug(
            _LOGGER,
            "__init__",
            "Button initialized",
            device=self._device_name,
            key=self._key,
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{DOMAIN}_{self._device_sn}_{self._key}"

    @property
    def suggested_object_id(self) -> str | None:
        """Return a stable English-based object ID regardless of HA language."""
        return self._key

    async def _wait_for_boost_state(self, expected_active: int) -> None:
        """Poll device every second until boost_active matches expected, or 3s timeout."""
        for attempt in range(1, 4):
            await asyncio.sleep(1.0)
            # Read device data directly to bypass coordinator throttling
            await self.coordinator.api.async_get_data()
            self.async_write_ha_state()
            actual = int(self.coordinator.api.data.get("boost_active", -1))
            log_debug(
                _LOGGER,
                "_wait_for_boost_state",
                "Checking boost state",
                attempt=attempt,
                expected=expected_active,
                actual=actual,
            )
            if actual == expected_active:
                # Notify all coordinator entities so UI reflects the new state immediately
                # rather than waiting for the next polling cycle.
                self.coordinator.async_set_updated_data(self.coordinator.data)
                return
        actual = self.coordinator.api.data.get("boost_active")
        log_warning(
            _LOGGER,
            "_wait_for_boost_state",
            "Boost state not confirmed after 3s",
            expected=expected_active,
            actual=actual,
        )
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="boost_command_timeout",
            translation_placeholders={"action": self._action},
        )

    async def async_press(self) -> None:
        """Handle button press."""
        log_debug(_LOGGER, "async_press", "Button pressed", key=self._key, action=self._action)
        if self._action == "boost_start":
            duration_min = int(
                self.coordinator.api.data.get("boost_duration", DEFAULT_BOOST_DURATION)
            )
            boost_level_pct = int(self.coordinator.api.data.get("boost_level", DEFAULT_BOOST_LEVEL))
            boost_power_bp = boost_level_pct * 100  # % → basis points (100% = 10000)
            log_debug(
                _LOGGER,
                "async_press",
                "Starting boost",
                duration_min=duration_min,
                boost_level_pct=boost_level_pct,
                boost_power_bp=boost_power_bp,
            )
            if not await self.coordinator.api.async_send_boost(boost_power_bp, duration_min * 60):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="boost_command_timeout",
                    translation_placeholders={"action": self._action},
                )
            await self._wait_for_boost_state(expected_active=1)
        elif self._action == "boost_cancel":
            if not await self.coordinator.api.async_send_boost(0, 1):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="boost_command_timeout",
                    translation_placeholders={"action": self._action},
                )
            await self._wait_for_boost_state(expected_active=0)
        elif self._action == "pr_force_off":
            if not await self.coordinator.api.async_send_boost(0, 65535):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="boost_command_timeout",
                    translation_placeholders={"action": self._action},
                )
            await self._wait_for_boost_state(expected_active=1)
        elif self._action == "refresh_pr_params":
            self.coordinator.api.reset_par_cache()
            await self.coordinator.async_refresh()
        elif self._action == "sync_clock":
            if not await self.coordinator.api.async_sync_clock():
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="clock_sync_failed",
                )
            await self.coordinator.async_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device specific attributes."""
        return DeviceInfo(
            hw_version=self._device_hwver,
            identifiers={(DOMAIN, self._device_sn)},
            manufacturer=self._device_manufact,
            model=self._device_model,
            name=self._device_name,
            serial_number=self._device_sn,
            sw_version=self._device_swver,
        )
