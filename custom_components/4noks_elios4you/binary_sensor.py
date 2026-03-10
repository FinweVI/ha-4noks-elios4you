"""Binary Sensor Platform for 4-noks Elios4You Power Reducer status.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

import logging
from typing import Any, cast

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Elios4YouConfigEntry
from .const import BINARY_SENSOR_ENTITIES, DOMAIN
from .coordinator import Elios4YouCoordinator
from .helpers import log_debug

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: Elios4YouConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Binary Sensor Platform setup."""
    coordinator = config_entry.runtime_data.coordinator
    entities = [
        Elios4YouBinarySensor(coordinator, cast(dict[str, Any], entity_def))
        for entity_def in BINARY_SENSOR_ENTITIES
        if entity_def["key"] in coordinator.api.data
    ]
    async_add_entities(entities)


class Elios4YouBinarySensor(CoordinatorEntity[Elios4YouCoordinator], BinarySensorEntity):
    """Binary sensor entity for Power Reducer boolean status fields."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Elios4YouCoordinator,
        entity_def: dict[str, Any],
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._key: str = entity_def["key"]
        self._attr_translation_key = self._key
        self._attr_icon = entity_def["icon"]
        self._attr_device_class = cast(BinarySensorDeviceClass | None, entity_def["device_class"])
        self._attr_entity_registry_enabled_default = entity_def["enabled_default"]
        # Operational state entities (e.g. boost_active) belong to the main entity list (None).
        # Diagnostic-only entities (e.g. pr_load_warning) go to DIAGNOSTIC.
        self._attr_entity_category = entity_def.get("entity_category")
        self._device_sn: str = str(coordinator.api.data.get("sn", ""))
        self._device_name: str = str(coordinator.api.name)
        self._device_model: str = str(coordinator.api.data.get("model", ""))
        self._device_manufact: str = str(coordinator.api.data.get("manufact", ""))
        self._device_hwver: str = str(coordinator.api.data.get("hwver", ""))
        self._device_swver: str = str(coordinator.api.data.get("swver", ""))
        log_debug(
            _LOGGER,
            "__init__",
            "Binary sensor initialized",
            device=coordinator.api.name,
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

    @property
    def is_on(self) -> bool | None:
        """Return True when the binary value is 1 (active/warning)."""
        val = self.coordinator.api.data.get(self._key)
        if val is None:
            return None
        return int(val) == 1

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

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
