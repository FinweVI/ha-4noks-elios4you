"""Tests for 4-noks Elios4you button module.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Direct imports using symlink (fournoks_elios4you -> 4noks_elios4you)
from custom_components.fournoks_elios4you.button import Elios4YouButton, async_setup_entry
from custom_components.fournoks_elios4you.const import (
    BUTTON_ENTITIES,
    CONF_SCAN_INTERVAL,
    DEFAULT_BOOST_DURATION,
    DEFAULT_BOOST_LEVEL,
    DOMAIN,
)
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
    coordinator.api.data["boost_active"] = 0
    coordinator.api.data["boost_duration"] = DEFAULT_BOOST_DURATION
    coordinator.api.data["boost_level"] = DEFAULT_BOOST_LEVEL
    coordinator.api.async_send_boost = AsyncMock(return_value=True)
    coordinator.api.async_sync_clock = AsyncMock(return_value=True)
    coordinator.api.async_get_data = AsyncMock(return_value=True)
    coordinator.api.reset_par_cache = MagicMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


@pytest.fixture
def boost_start_entity_def():
    """Return the entity definition for boost_start button."""
    return next(e for e in BUTTON_ENTITIES if e["key"] == "boost_start")


@pytest.fixture
def boost_cancel_entity_def():
    """Return the entity definition for boost_cancel button."""
    return next(e for e in BUTTON_ENTITIES if e["key"] == "boost_cancel")


@pytest.fixture
def pr_force_off_entity_def():
    """Return the entity definition for pr_force_off button."""
    return next(e for e in BUTTON_ENTITIES if e["key"] == "pr_force_off")


@pytest.fixture
def refresh_pr_params_entity_def():
    """Return the entity definition for refresh_pr_params button."""
    return next(e for e in BUTTON_ENTITIES if e["key"] == "refresh_pr_params")


@pytest.fixture
def sync_clock_entity_def():
    """Return the entity definition for sync_clock button."""
    return next(e for e in BUTTON_ENTITIES if e["key"] == "sync_clock")


class TestButtonSetup:
    """Tests for button platform setup."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_all_buttons(
        self, hass: HomeAssistant, mock_coordinator
    ) -> None:
        """Test that setup creates all button entities."""
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

        assert len(entities) == len(BUTTON_ENTITIES)
        assert all(isinstance(e, Elios4YouButton) for e in entities)


class TestButtonEntity:
    """Tests for Elios4YouButton entity properties."""

    def test_init_boost_start(self, mock_coordinator, boost_start_entity_def) -> None:
        """Test button initialization for boost_start."""
        button = Elios4YouButton(mock_coordinator, boost_start_entity_def)

        assert button._key == "boost_start"
        assert button._action == "boost_start"
        assert button._attr_translation_key == "boost_start"
        assert button._attr_entity_category is None  # operational
        assert button._attr_entity_registry_enabled_default is False
        assert button._device_sn == TEST_SERIAL_NUMBER
        assert button._device_name == TEST_NAME

    def test_init_refresh_pr_params_is_diagnostic(
        self, mock_coordinator, refresh_pr_params_entity_def
    ) -> None:
        """Test refresh_pr_params button gets DIAGNOSTIC entity_category."""
        button = Elios4YouButton(mock_coordinator, refresh_pr_params_entity_def)

        assert button._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_init_sync_clock_is_diagnostic(self, mock_coordinator, sync_clock_entity_def) -> None:
        """Test sync_clock button gets DIAGNOSTIC entity_category."""
        button = Elios4YouButton(mock_coordinator, sync_clock_entity_def)

        assert button._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_unique_id(self, mock_coordinator, boost_start_entity_def) -> None:
        """Test unique_id is constructed from domain, serial number, and key."""
        button = Elios4YouButton(mock_coordinator, boost_start_entity_def)

        assert button.unique_id == f"{DOMAIN}_{TEST_SERIAL_NUMBER}_boost_start"

    def test_suggested_object_id(self, mock_coordinator, boost_start_entity_def) -> None:
        """Test suggested_object_id returns the entity key."""
        button = Elios4YouButton(mock_coordinator, boost_start_entity_def)

        assert button.suggested_object_id == "boost_start"

    def test_device_info(self, mock_coordinator, boost_start_entity_def) -> None:
        """Test device_info returns correct DeviceInfo."""
        button = Elios4YouButton(mock_coordinator, boost_start_entity_def)
        info = button.device_info

        assert (DOMAIN, TEST_SERIAL_NUMBER) in info["identifiers"]
        assert info["name"] == TEST_NAME
        assert info["manufacturer"] == "4-noks"
        assert info["model"] == "Elios4you"

    def test_has_entity_name(self, mock_coordinator, boost_start_entity_def) -> None:
        """Test _attr_has_entity_name is True."""
        button = Elios4YouButton(mock_coordinator, boost_start_entity_def)

        assert button._attr_has_entity_name is True


class TestButtonPress:
    """Tests for button async_press actions."""

    @pytest.mark.asyncio
    async def test_boost_start_calls_send_boost(
        self, mock_coordinator, boost_start_entity_def
    ) -> None:
        """Test boost_start sends correct boost command."""
        mock_coordinator.api.data["boost_active"] = 1  # Confirms state after press
        button = Elios4YouButton(mock_coordinator, boost_start_entity_def)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        expected_power_bp = DEFAULT_BOOST_LEVEL * 100
        expected_duration_s = DEFAULT_BOOST_DURATION * 60
        mock_coordinator.api.async_send_boost.assert_called_once_with(
            expected_power_bp, expected_duration_s
        )

    @pytest.mark.asyncio
    async def test_boost_start_raises_on_send_failure(
        self, mock_coordinator, boost_start_entity_def
    ) -> None:
        """Test boost_start raises HomeAssistantError when send_boost fails."""
        mock_coordinator.api.async_send_boost = AsyncMock(return_value=False)
        button = Elios4YouButton(mock_coordinator, boost_start_entity_def)

        with pytest.raises(HomeAssistantError):
            await button.async_press()

    @pytest.mark.asyncio
    async def test_boost_cancel_sends_zero_boost(
        self, mock_coordinator, boost_cancel_entity_def
    ) -> None:
        """Test boost_cancel sends boost(0, 1) to cancel."""
        mock_coordinator.api.data["boost_active"] = 0  # Confirms state after cancel
        button = Elios4YouButton(mock_coordinator, boost_cancel_entity_def)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        mock_coordinator.api.async_send_boost.assert_called_once_with(0, 1)

    @pytest.mark.asyncio
    async def test_boost_cancel_raises_on_send_failure(
        self, mock_coordinator, boost_cancel_entity_def
    ) -> None:
        """Test boost_cancel raises HomeAssistantError when send_boost fails."""
        mock_coordinator.api.async_send_boost = AsyncMock(return_value=False)
        button = Elios4YouButton(mock_coordinator, boost_cancel_entity_def)

        with pytest.raises(HomeAssistantError):
            await button.async_press()

    @pytest.mark.asyncio
    async def test_pr_force_off_sends_max_duration(
        self, mock_coordinator, pr_force_off_entity_def
    ) -> None:
        """Test pr_force_off sends boost(0, 65535) to force off."""
        mock_coordinator.api.data["boost_active"] = 1  # Force off enters "boost" mode
        button = Elios4YouButton(mock_coordinator, pr_force_off_entity_def)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await button.async_press()

        mock_coordinator.api.async_send_boost.assert_called_once_with(0, 65535)

    @pytest.mark.asyncio
    async def test_pr_force_off_raises_on_send_failure(
        self, mock_coordinator, pr_force_off_entity_def
    ) -> None:
        """Test pr_force_off raises HomeAssistantError when send_boost fails."""
        mock_coordinator.api.async_send_boost = AsyncMock(return_value=False)
        button = Elios4YouButton(mock_coordinator, pr_force_off_entity_def)

        with pytest.raises(HomeAssistantError):
            await button.async_press()

    @pytest.mark.asyncio
    async def test_refresh_pr_params_resets_cache_and_refreshes(
        self, mock_coordinator, refresh_pr_params_entity_def
    ) -> None:
        """Test refresh_pr_params resets par cache and triggers coordinator refresh."""
        button = Elios4YouButton(mock_coordinator, refresh_pr_params_entity_def)

        await button.async_press()

        mock_coordinator.api.reset_par_cache.assert_called_once()
        mock_coordinator.async_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_clock_success(self, mock_coordinator, sync_clock_entity_def) -> None:
        """Test sync_clock calls async_sync_clock and refreshes coordinator."""
        button = Elios4YouButton(mock_coordinator, sync_clock_entity_def)

        await button.async_press()

        mock_coordinator.api.async_sync_clock.assert_called_once()
        mock_coordinator.async_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_clock_raises_on_failure(
        self, mock_coordinator, sync_clock_entity_def
    ) -> None:
        """Test sync_clock raises HomeAssistantError when sync fails."""
        mock_coordinator.api.async_sync_clock = AsyncMock(return_value=False)
        button = Elios4YouButton(mock_coordinator, sync_clock_entity_def)

        with pytest.raises(HomeAssistantError):
            await button.async_press()


class TestWaitForBoostState:
    """Tests for _wait_for_boost_state polling logic."""

    @pytest.mark.asyncio
    async def test_wait_confirms_state_immediately(
        self, mock_coordinator, boost_start_entity_def
    ) -> None:
        """Test _wait_for_boost_state succeeds when state matches on first poll."""
        mock_coordinator.api.data["boost_active"] = 1
        button = Elios4YouButton(mock_coordinator, boost_start_entity_def)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await button._wait_for_boost_state(expected_active=1)

        mock_coordinator.async_set_updated_data.assert_called_once_with(mock_coordinator.api.data)

    @pytest.mark.asyncio
    async def test_wait_raises_on_timeout(self, mock_coordinator, boost_start_entity_def) -> None:
        """Test _wait_for_boost_state raises HomeAssistantError after 3 failed polls."""
        # boost_active stays at 0, never reaches expected=1
        mock_coordinator.api.data["boost_active"] = 0
        button = Elios4YouButton(mock_coordinator, boost_start_entity_def)

        with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(HomeAssistantError):
            await button._wait_for_boost_state(expected_active=1)

        # Should have polled 3 times
        assert mock_coordinator.api.async_get_data.call_count == 3
