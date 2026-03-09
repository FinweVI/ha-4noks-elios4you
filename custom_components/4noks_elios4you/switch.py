"""Switch Platform Device for 4-noks Elios4You.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Elios4YouConfigEntry
from .const import DOMAIN, SWITCH_ENTITIES
from .coordinator import Elios4YouCoordinator
from .helpers import log_debug

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: Elios4YouConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Switch Platform setup."""

    # This gets the data update coordinator from hass.data as specified in your __init__.py
    coordinator = config_entry.runtime_data.coordinator

    # Add defined switches using list comprehension
    switches = [
        Elios4YouSwitch(
            coordinator,
            switch["name"],
            switch["key"],
            switch["icon"],
            switch["device_class"],
        )
        for switch in SWITCH_ENTITIES
        if coordinator.api.data[switch["key"]] is not None
    ]

    async_add_entities(switches)


class Elios4YouSwitch(CoordinatorEntity[Elios4YouCoordinator], SwitchEntity):
    """Switch to set the status of the Wiser Operation Mode (Away/Normal)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Elios4YouCoordinator,
        name: str,
        key: str,
        icon: str,
        device_class: SwitchDeviceClass | str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._key = key
        self._icon = icon
        self._device_class = device_class
        self._is_on = self.coordinator.api.data["relay_state"]
        self._device_name: str = str(self.coordinator.api.name)
        self._device_host = self.coordinator.api.host
        self._device_model: str = str(self.coordinator.api.data["model"])
        self._device_manufact: str = str(self.coordinator.api.data["manufact"])
        self._device_sn: str = str(self.coordinator.api.data["sn"])
        self._device_swver: str = str(self.coordinator.api.data["swver"])
        self._device_hwver: str = str(self.coordinator.api.data["hwver"])
        # Use translation key for entity name (translations in translations/*.json)
        self._attr_translation_key = key
        log_debug(
            _LOGGER,
            "__init__",
            "Switch initialized",
            device=self.coordinator.api.name,
            key=self._key,
        )

    @property
    def suggested_object_id(self) -> str | None:
        """Return a stable English-based object ID regardless of HA language."""
        return self._key

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._is_on = self.coordinator.api.data["relay_state"]
        self.async_write_ha_state()
        log_debug(
            _LOGGER,
            "_handle_coordinator_update",
            "Switch coordinator update requested",
            key=self._key,
        )

    @property
    def icon(self) -> str:
        """Return icon."""
        return self._icon

    @property
    def device_class(self) -> SwitchDeviceClass:
        """Return the switch device_class."""
        return self._device_class  # type: ignore[return-value]

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{DOMAIN}_{self._device_sn}_{self._key}"

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        log_debug(_LOGGER, "async_turn_on", "Turning relay on")
        # telnet_set_relay sends the command, reads back @rel to verify, and updates
        # api.data["relay_state"] — its return value is the confirmation.
        if not await self.coordinator.api.telnet_set_relay("on"):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="relay_command_timeout",
            )
        self._handle_coordinator_update()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        log_debug(_LOGGER, "async_turn_off", "Turning relay off")
        if not await self.coordinator.api.telnet_set_relay("off"):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="relay_command_timeout",
            )
        self._handle_coordinator_update()

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
