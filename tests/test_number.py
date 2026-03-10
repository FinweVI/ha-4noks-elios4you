"""Tests for 4-noks Elios4you number module.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# Direct imports using symlink (fournoks_elios4you -> 4noks_elios4you)
from custom_components.fournoks_elios4you.const import CONF_SCAN_INTERVAL, DOMAIN, NUMBER_ENTITIES
from custom_components.fournoks_elios4you.number import Elios4YouNumber, async_setup_entry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    coordinator.api.data["spf_ldw"] = 500
    coordinator.api.data["spf_spw"] = 200
    coordinator.api.data["boost_duration"] = 120
    coordinator.api.data["boost_level"] = 100
    coordinator.api.async_write_par = AsyncMock(return_value=True)
    coordinator.async_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def spf_ldw_entity_def():
    """Return the entity definition for spf_ldw (device PAR param)."""
    return next(e for e in NUMBER_ENTITIES if e["key"] == "spf_ldw")


@pytest.fixture
def boost_duration_entity_def():
    """Return the entity definition for boost_duration (local-only param)."""
    return next(e for e in NUMBER_ENTITIES if e["key"] == "boost_duration")


@pytest.fixture
def boost_level_entity_def():
    """Return the entity definition for boost_level (local-only param)."""
    return next(e for e in NUMBER_ENTITIES if e["key"] == "boost_level")


class TestNumberSetup:
    """Tests for number platform setup."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_all_numbers(
        self, hass: HomeAssistant, mock_coordinator
    ) -> None:
        """Test that setup creates all number entities."""
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

        assert len(entities) == len(NUMBER_ENTITIES)
        assert all(isinstance(e, Elios4YouNumber) for e in entities)


class TestNumberEntity:
    """Tests for Elios4YouNumber entity properties."""

    def test_init_spf_ldw(self, mock_coordinator, spf_ldw_entity_def) -> None:
        """Test number entity initialization for spf_ldw (device PAR)."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        assert number._key == "spf_ldw"
        assert number._par_param == "SPF_LDW"
        assert number._attr_translation_key == "spf_ldw"
        assert number._attr_entity_category == EntityCategory.CONFIG
        assert number._attr_entity_registry_enabled_default is False
        assert number._attr_native_min_value == 0.0
        assert number._attr_native_max_value == 10000.0
        assert number._attr_native_step == 50.0
        assert number._device_sn == TEST_SERIAL_NUMBER
        assert number._device_name == TEST_NAME

    def test_init_boost_duration_has_no_par_param(
        self, mock_coordinator, boost_duration_entity_def
    ) -> None:
        """Test boost_duration is local-only (no par_param)."""
        number = Elios4YouNumber(mock_coordinator, boost_duration_entity_def)

        assert number._key == "boost_duration"
        assert number._par_param is None

    def test_unique_id(self, mock_coordinator, spf_ldw_entity_def) -> None:
        """Test unique_id is constructed from domain, serial number, and key."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        assert number.unique_id == f"{DOMAIN}_{TEST_SERIAL_NUMBER}_spf_ldw"

    def test_suggested_object_id(self, mock_coordinator, spf_ldw_entity_def) -> None:
        """Test suggested_object_id returns the entity key."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        assert number.suggested_object_id == "spf_ldw"

    def test_native_value_returns_float(self, mock_coordinator, spf_ldw_entity_def) -> None:
        """Test native_value converts stored value to float."""
        mock_coordinator.api.data["spf_ldw"] = 750
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        assert number.native_value == 750.0
        assert isinstance(number.native_value, float)

    def test_native_value_returns_none_when_key_missing(
        self, mock_coordinator, spf_ldw_entity_def
    ) -> None:
        """Test native_value returns None when key absent from data."""
        mock_coordinator.api.data.pop("spf_ldw", None)
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        assert number.native_value is None

    def test_device_info(self, mock_coordinator, spf_ldw_entity_def) -> None:
        """Test device_info returns correct DeviceInfo."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)
        info = number.device_info

        assert (DOMAIN, TEST_SERIAL_NUMBER) in info["identifiers"]
        assert info["name"] == TEST_NAME
        assert info["manufacturer"] == "4-noks"
        assert info["model"] == "Elios4you"

    def test_has_entity_name(self, mock_coordinator, spf_ldw_entity_def) -> None:
        """Test _attr_has_entity_name is True."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        assert number._attr_has_entity_name is True


class TestNumberSetValue:
    """Tests for async_set_native_value."""

    @pytest.mark.asyncio
    async def test_set_value_writes_to_device_when_par_param(
        self, mock_coordinator, spf_ldw_entity_def
    ) -> None:
        """Test that setting a value with par_param writes to device and refreshes."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        await number.async_set_native_value(750.0)

        mock_coordinator.api.async_write_par.assert_called_once_with("SPF_LDW", 750)
        mock_coordinator.async_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_updates_local_data_when_no_par_param(
        self, mock_coordinator, boost_duration_entity_def
    ) -> None:
        """Test that local-only values update api.data without device command."""
        number = Elios4YouNumber(mock_coordinator, boost_duration_entity_def)
        number.async_write_ha_state = MagicMock()

        await number.async_set_native_value(90.0)

        mock_coordinator.api.async_write_par.assert_not_called()
        mock_coordinator.async_refresh.assert_not_called()
        assert mock_coordinator.api.data["boost_duration"] == 90
        number.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_raises_on_out_of_range_low(
        self, mock_coordinator, spf_ldw_entity_def
    ) -> None:
        """Test that values below min raise HomeAssistantError."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        with pytest.raises(HomeAssistantError):
            await number.async_set_native_value(-1.0)

        mock_coordinator.api.async_write_par.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_value_raises_on_out_of_range_high(
        self, mock_coordinator, spf_ldw_entity_def
    ) -> None:
        """Test that values above max raise HomeAssistantError."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        with pytest.raises(HomeAssistantError):
            await number.async_set_native_value(99999.0)

        mock_coordinator.api.async_write_par.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_value_at_min_boundary_accepted(
        self, mock_coordinator, spf_ldw_entity_def
    ) -> None:
        """Test that the minimum boundary value is accepted."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        await number.async_set_native_value(0.0)  # min is 0

        mock_coordinator.api.async_write_par.assert_called_once_with("SPF_LDW", 0)

    @pytest.mark.asyncio
    async def test_set_value_at_max_boundary_accepted(
        self, mock_coordinator, spf_ldw_entity_def
    ) -> None:
        """Test that the maximum boundary value is accepted."""
        number = Elios4YouNumber(mock_coordinator, spf_ldw_entity_def)

        await number.async_set_native_value(10000.0)  # max is 10000

        mock_coordinator.api.async_write_par.assert_called_once_with("SPF_LDW", 10000)

    @pytest.mark.asyncio
    async def test_boost_level_local_update(
        self, mock_coordinator, boost_level_entity_def
    ) -> None:
        """Test boost_level local-only update (no par_param)."""
        number = Elios4YouNumber(mock_coordinator, boost_level_entity_def)
        number.async_write_ha_state = MagicMock()

        await number.async_set_native_value(50.0)

        mock_coordinator.api.async_write_par.assert_not_called()
        assert mock_coordinator.api.data["boost_level"] == 50
        number.async_write_ha_state.assert_called_once()
