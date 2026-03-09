"""Sensor Platform Device for 4-noks Elios4You.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

import logging
from typing import Any, cast

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Elios4YouConfigEntry
from .const import CONF_NAME, DOMAIN, SENSOR_ENTITIES
from .coordinator import Elios4YouCoordinator
from .helpers import log_debug

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: Elios4YouConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensor Platform setup."""
    # This gets the data update coordinator from hass.data as specified in your __init__.py
    coordinator = config_entry.runtime_data.coordinator

    log_debug(
        _LOGGER,
        "async_setup_entry",
        "Setting up sensors",
        name=config_entry.data.get(CONF_NAME),
        manufacturer=coordinator.api.data["manufact"],
        model=coordinator.api.data["model"],
        hw_version=coordinator.api.data["hwver"],
        sw_version=coordinator.api.data["swver"],
        serial_number=coordinator.api.data["sn"],
    )

    sensors = []
    for sensor in SENSOR_ENTITIES:
        sensor_def = cast(dict[str, Any], sensor)
        if coordinator.api.data[sensor_def["key"]] is not None:
            sensors.append(
                Elios4YouSensor(
                    coordinator,
                    sensor_def["name"],
                    sensor_def["key"],
                    sensor_def["icon"],
                    sensor_def["device_class"],
                    sensor_def["state_class"],
                    sensor_def["unit"],
                    sensor_def["enabled_default"],
                    sensor_def.get("options"),
                    sensor_def.get("entity_category"),
                )
            )

    async_add_entities(sensors)


class Elios4YouSensor(CoordinatorEntity[Elios4YouCoordinator], SensorEntity):
    """Representation of an Elios4You sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Elios4YouCoordinator,
        name: str,
        key: str,
        icon: str,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
        unit: str | None,
        enabled_default: bool,
        options: list[str] | None = None,
        entity_category_override: EntityCategory | None = None,
    ) -> None:
        """Class Initializitation."""
        super().__init__(coordinator)
        self._key = key
        self._icon = icon
        self._device_class = device_class
        self._state_class = state_class
        self._unit_of_measurement = unit
        self._entity_category_override = entity_category_override
        self._device_name: str = self.coordinator.api.name
        self._device_host: str = self.coordinator.api.host
        self._device_model: str = str(self.coordinator.api.data.get("model", ""))
        self._device_manufact: str = str(self.coordinator.api.data.get("manufact", ""))
        self._device_sn: str = str(self.coordinator.api.data.get("sn", ""))
        self._device_swver: str = str(self.coordinator.api.data.get("swver", ""))
        self._device_hwver: str = str(self.coordinator.api.data.get("hwver", ""))
        # Use translation key for entity name (translations in translations/*.json)
        self._attr_translation_key = key
        # Entity registry enabled default (False = disabled by default in UI)
        self._attr_entity_registry_enabled_default = enabled_default
        # ENUM sensors require options list
        if options is not None:
            self._attr_options = options

    @property
    def suggested_object_id(self) -> str | None:
        """Return a stable English-based object ID regardless of HA language."""
        return self._key

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fetch new state data for the sensor."""
        self._state = self.coordinator.api.data[self._key]
        self.async_write_ha_state()
        # write debug log only on first sensor to avoid spamming the log
        if self._key == "rcap":
            log_debug(
                _LOGGER,
                "_handle_coordinator_update",
                "Sensors state written to state machine",
            )

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self) -> str:
        """Return the sensor icon."""
        return self._icon

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the sensor device_class."""
        return self._device_class

    @property
    def state_class(self) -> SensorStateClass | None:
        """Return the sensor state_class."""
        return self._state_class

    @property
    def entity_category(self) -> EntityCategory | None:
        """Return the sensor entity_category."""
        # Explicit override from sensor definition takes precedence.
        if self._entity_category_override is not None:
            return self._entity_category_override
        # ENUM sensors represent operational state (e.g. Power Reducer Mode), not diagnostics.
        if self._device_class == SensorDeviceClass.ENUM:
            return None
        if self._state_class is None:
            return EntityCategory.DIAGNOSTIC
        return None

    @property
    def native_value(self) -> int | float | str | None:
        """Return the state of the sensor."""
        if self._key in self.coordinator.api.data:
            return self.coordinator.api.data[self._key]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the extra state attributes."""
        return None

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this entity."""
        return f"{DOMAIN}_{self._device_sn}_{self._key}"

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
