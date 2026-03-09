"""Number Platform for 4-noks Elios4You Power Reducer parameters.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

import logging
from typing import Any, cast

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Elios4YouConfigEntry
from .const import DOMAIN, NUMBER_ENTITIES
from .coordinator import Elios4YouCoordinator
from .helpers import log_debug

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: Elios4YouConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Number Platform setup."""
    coordinator = config_entry.runtime_data.coordinator
    numbers = [
        Elios4YouNumber(coordinator, cast(dict[str, Any], entity_def))
        for entity_def in NUMBER_ENTITIES
    ]
    async_add_entities(numbers)


class Elios4YouNumber(CoordinatorEntity[Elios4YouCoordinator], NumberEntity):
    """Number entity for Power Reducer configuration parameters."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Elios4YouCoordinator,
        entity_def: dict[str, Any],
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._key: str = entity_def["key"]
        self._par_param: str | None = entity_def.get("par_param")
        self._attr_translation_key = self._key
        self._attr_icon = entity_def["icon"]
        self._attr_native_min_value = float(entity_def["min"])
        self._attr_native_max_value = float(entity_def["max"])
        self._attr_native_step = float(entity_def["step"])
        self._attr_native_unit_of_measurement = entity_def["unit"]
        self._attr_mode = entity_def["mode"]
        self._attr_entity_category = EntityCategory.CONFIG
        # All number entities are Power Reducer-specific; disabled by default until PR option is enabled.
        self._attr_entity_registry_enabled_default = False
        self._device_sn: str = str(coordinator.api.data.get("sn", ""))
        self._device_name: str = str(coordinator.api.name)
        self._device_model: str = str(coordinator.api.data.get("model", ""))
        self._device_manufact: str = str(coordinator.api.data.get("manufact", ""))
        self._device_hwver: str = str(coordinator.api.data.get("hwver", ""))
        self._device_swver: str = str(coordinator.api.data.get("swver", ""))
        log_debug(
            _LOGGER,
            "__init__",
            "Number entity initialized",
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
    def native_value(self) -> float | None:
        """Return the current value."""
        val = self.coordinator.api.data.get(self._key)
        if val is None:
            return None
        return float(val)

    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        int_value = int(value)
        # Re-validate bounds server-side — HA's UI enforces them but direct service calls do not
        if int_value < int(self._attr_native_min_value) or int_value > int(
            self._attr_native_max_value
        ):
            log_debug(
                _LOGGER,
                "async_set_native_value",
                "Value out of range, rejected",
                key=self._key,
                value=int_value,
                min=self._attr_native_min_value,
                max=self._attr_native_max_value,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="number_out_of_range",
                translation_placeholders={
                    "value": str(int_value),
                    "min": str(int(self._attr_native_min_value)),
                    "max": str(int(self._attr_native_max_value)),
                    "key": self._key,
                },
            )
        if self._par_param is not None:
            # Device parameter: write to device then refresh
            success = await self.coordinator.api.async_write_par(self._par_param, int_value)
            log_debug(
                _LOGGER,
                "async_set_native_value",
                "Device PAR set",
                key=self._key,
                value=int_value,
                success=success,
            )
            await self.coordinator.async_refresh()
        else:
            # Local-only parameter: update api.data directly, no device command
            self.coordinator.api.data[self._key] = int_value
            self.async_write_ha_state()
            log_debug(
                _LOGGER,
                "async_set_native_value",
                "Local-only value updated",
                key=self._key,
                value=int_value,
            )

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
