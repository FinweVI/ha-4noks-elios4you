"""Tests for 4-noks Elios4you binary_sensor module.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# Direct imports using symlink (fournoks_elios4you -> 4noks_elios4you)
from custom_components.fournoks_elios4you.binary_sensor import (
    Elios4YouBinarySensor,
    async_setup_entry,
)
from custom_components.fournoks_elios4you.const import (
    BINARY_SENSOR_ENTITIES,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .conftest import TEST_HOST, TEST_NAME, TEST_PORT, TEST_SCAN_INTERVAL, TEST_SERIAL_NUMBER
from .test_config_flow import MockConfigEntry


@pytest.fixture
def mock_coordinator(mock_api_data):
    """Create a mock coordinator with API data."""
    coordinator = MagicMock()
    coordinator.api = MagicMock()
    coordinator.api.name = TEST_NAME
    coordinator.api.host = TEST_HOST
    coordinator.api.data = mock_api_data
    coordinator.api.data["model"] = "Elios4you"
    coordinator.api.data["manufact"] = "4-noks"
    coordinator.api.data["sn"] = TEST_SERIAL_NUMBER
    coordinator.api.data["swver"] = "1.0"
    coordinator.api.data["hwver"] = "2.0"
    coordinator.api.data["boost_active"] = 0
    coordinator.api.data["pr_load_warning"] = 0
    return coordinator


@pytest.fixture
def boost_active_entity_def():
    """Return the entity definition for boost_active."""
    return next(e for e in BINARY_SENSOR_ENTITIES if e["key"] == "boost_active")


@pytest.fixture
def pr_load_warning_entity_def():
    """Return the entity definition for pr_load_warning."""
    return next(e for e in BINARY_SENSOR_ENTITIES if e["key"] == "pr_load_warning")


class TestBinarySensorSetup:
    """Tests for binary sensor platform setup."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_sensors(
        self, hass: HomeAssistant, mock_coordinator
    ) -> None:
        """Test that setup creates binary sensor entities for keys present in data."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_NAME: TEST_NAME, CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT},
            options={CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL},
        )
        entry.add_to_hass(hass)
        runtime_data = MagicMock()
        runtime_data.coordinator = mock_coordinator
        entry.runtime_data = runtime_data

        entities = []

        def async_add_entities(new_entities):
            entities.extend(new_entities)

        await async_setup_entry(hass, entry, async_add_entities)

        assert len(entities) == len(BINARY_SENSOR_ENTITIES)
        assert all(isinstance(e, Elios4YouBinarySensor) for e in entities)

    @pytest.mark.asyncio
    async def test_async_setup_entry_skips_missing_keys(
        self, hass: HomeAssistant, mock_coordinator
    ) -> None:
        """Test that setup skips entities whose key is not in coordinator data."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_NAME: TEST_NAME, CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT},
            options={CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL},
        )
        entry.add_to_hass(hass)

        # Remove all PR binary sensor keys from data
        for entity_def in BINARY_SENSOR_ENTITIES:
            mock_coordinator.api.data.pop(entity_def["key"], None)

        runtime_data = MagicMock()
        runtime_data.coordinator = mock_coordinator
        entry.runtime_data = runtime_data

        entities = []

        def async_add_entities(new_entities):
            entities.extend(new_entities)

        await async_setup_entry(hass, entry, async_add_entities)

        assert len(entities) == 0


class TestBinarySensorEntity:
    """Tests for Elios4YouBinarySensor entity."""

    def test_init_boost_active(self, mock_coordinator, boost_active_entity_def) -> None:
        """Test binary sensor initialization for boost_active."""
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)

        assert sensor._key == "boost_active"
        assert sensor._attr_translation_key == "boost_active"
        assert sensor._attr_icon == boost_active_entity_def["icon"]
        assert sensor._attr_device_class == BinarySensorDeviceClass.RUNNING
        assert sensor._attr_entity_category is None  # operational state
        assert sensor._device_sn == TEST_SERIAL_NUMBER
        assert sensor._device_name == TEST_NAME

    def test_init_pr_load_warning(self, mock_coordinator, pr_load_warning_entity_def) -> None:
        """Test binary sensor initialization for pr_load_warning (diagnostic)."""
        sensor = Elios4YouBinarySensor(mock_coordinator, pr_load_warning_entity_def)

        assert sensor._key == "pr_load_warning"
        assert sensor._attr_device_class is None
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_unique_id(self, mock_coordinator, boost_active_entity_def) -> None:
        """Test unique_id is constructed from domain, serial number, and key."""
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)

        assert sensor.unique_id == f"{DOMAIN}_{TEST_SERIAL_NUMBER}_boost_active"

    def test_suggested_object_id(self, mock_coordinator, boost_active_entity_def) -> None:
        """Test suggested_object_id returns the entity key."""
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)

        assert sensor.suggested_object_id == "boost_active"

    def test_is_on_returns_true_when_value_is_1(
        self, mock_coordinator, boost_active_entity_def
    ) -> None:
        """Test is_on returns True when data value is 1."""
        mock_coordinator.api.data["boost_active"] = 1
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)

        assert sensor.is_on is True

    def test_is_on_returns_false_when_value_is_0(
        self, mock_coordinator, boost_active_entity_def
    ) -> None:
        """Test is_on returns False when data value is 0."""
        mock_coordinator.api.data["boost_active"] = 0
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)

        assert sensor.is_on is False

    def test_is_on_returns_none_when_key_missing(
        self, mock_coordinator, boost_active_entity_def
    ) -> None:
        """Test is_on returns None when key is absent from data."""
        mock_coordinator.api.data.pop("boost_active", None)
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)

        assert sensor.is_on is None

    def test_is_on_string_value(self, mock_coordinator, boost_active_entity_def) -> None:
        """Test is_on handles string '1' and '0' correctly."""
        mock_coordinator.api.data["boost_active"] = "1"
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)
        assert sensor.is_on is True

        mock_coordinator.api.data["boost_active"] = "0"
        assert sensor.is_on is False

    def test_handle_coordinator_update(self, mock_coordinator, boost_active_entity_def) -> None:
        """Test _handle_coordinator_update calls async_write_ha_state."""
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)
        sensor.async_write_ha_state = MagicMock()

        sensor._handle_coordinator_update()

        sensor.async_write_ha_state.assert_called_once()

    def test_device_info(self, mock_coordinator, boost_active_entity_def) -> None:
        """Test device_info returns correct DeviceInfo."""
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)
        info = sensor.device_info

        assert (DOMAIN, TEST_SERIAL_NUMBER) in info["identifiers"]
        assert info["name"] == TEST_NAME
        assert info["manufacturer"] == "4-noks"
        assert info["model"] == "Elios4you"
        assert info["serial_number"] == TEST_SERIAL_NUMBER

    def test_entity_registry_enabled_default_boost_active(
        self, mock_coordinator, boost_active_entity_def
    ) -> None:
        """Test boost_active is disabled by default."""
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)

        assert sensor._attr_entity_registry_enabled_default is False

    def test_entity_has_entity_name(self, mock_coordinator, boost_active_entity_def) -> None:
        """Test _attr_has_entity_name is True."""
        sensor = Elios4YouBinarySensor(mock_coordinator, boost_active_entity_def)

        assert sensor._attr_has_entity_name is True
