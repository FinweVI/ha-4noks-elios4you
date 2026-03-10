"""Tests for 4-noks Elios4you integration setup.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Direct imports using symlink (fournoks_elios4you -> 4noks_elios4you)
from custom_components.fournoks_elios4you import (
    RuntimeData,
    _async_apply_pr_entity_state,
    _register_schedule_services,
    async_migrate_entry,
    async_remove_config_entry_device,
    async_setup,
    async_setup_entry,
    async_unload_entry,
    async_update_device_registry,
    coordinator as _elios4you_coordinator,
)
from custom_components.fournoks_elios4you.const import (
    CONF_ENABLE_REPAIR_NOTIFICATION,
    CONF_FAILURES_THRESHOLD,
    CONF_POWER_REDUCER,
    CONF_RECOVERY_SCRIPT,
    CONF_SCAN_INTERVAL,
    DEFAULT_ENABLE_REPAIR_NOTIFICATION,
    DEFAULT_FAILURES_THRESHOLD,
    DEFAULT_RECOVERY_SCRIPT,
    DOMAIN,
    PR_ENTITY_KEYS,
)
from custom_components.fournoks_elios4you.coordinator import Elios4YouCoordinator
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .conftest import TEST_HOST, TEST_NAME, TEST_PORT, TEST_SCAN_INTERVAL, TEST_SERIAL_NUMBER
from .test_config_flow import MockConfigEntry


async def test_async_setup_entry_success(
    hass: HomeAssistant,
    mock_elios4you_api,
    mock_api_data,
) -> None:
    """Test successful setup of config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: TEST_NAME,
            CONF_HOST: TEST_HOST,
            CONF_PORT: TEST_PORT,
        },
        options={
            CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL,
        },
    )
    entry.add_to_hass(hass)

    # Mock the API, coordinator's first refresh, and platform loading
    with (
        patch.object(
            _elios4you_coordinator,
            "Elios4YouAPI",
            return_value=mock_elios4you_api.return_value,
        ),
        patch.object(
            Elios4YouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new_callable=AsyncMock,
        ),
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    assert entry.runtime_data is not None


async def test_async_unload_entry(
    hass: HomeAssistant,
    mock_elios4you_api,
) -> None:
    """Test successful unload of config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: TEST_NAME,
            CONF_HOST: TEST_HOST,
            CONF_PORT: TEST_PORT,
        },
        options={
            CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL,
        },
    )
    entry.add_to_hass(hass)

    # Mock the API, coordinator's first refresh, and platform loading
    with (
        patch.object(
            _elios4you_coordinator,
            "Elios4YouAPI",
            return_value=mock_elios4you_api.return_value,
        ),
        patch.object(
            Elios4YouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new_callable=AsyncMock,
        ),
        patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await async_setup_entry(hass, entry)
        result = await async_unload_entry(hass, entry)

    assert result is True


async def test_migration_v1_to_v3(
    hass: HomeAssistant,
) -> None:
    """Test migration from v1 to v3 moves scan_interval and adds new options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: TEST_NAME,
            CONF_HOST: TEST_HOST,
            CONF_PORT: TEST_PORT,
            CONF_SCAN_INTERVAL: 90,  # v1 had scan_interval in data
        },
        options={},
        version=1,
    )
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is True
    assert entry.version == 3
    assert CONF_SCAN_INTERVAL not in entry.data
    assert entry.options.get(CONF_SCAN_INTERVAL) == 90
    # v3 adds new repair notification options with defaults
    assert entry.options.get(CONF_ENABLE_REPAIR_NOTIFICATION) == DEFAULT_ENABLE_REPAIR_NOTIFICATION
    assert entry.options.get(CONF_FAILURES_THRESHOLD) == DEFAULT_FAILURES_THRESHOLD
    assert entry.options.get(CONF_RECOVERY_SCRIPT) == DEFAULT_RECOVERY_SCRIPT


async def test_migration_v1_to_v3_no_scan_interval(
    hass: HomeAssistant,
) -> None:
    """Test migration from v1 to v3 when scan_interval not in data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: TEST_NAME,
            CONF_HOST: TEST_HOST,
            CONF_PORT: TEST_PORT,
        },
        options={},
        version=1,
    )
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is True
    assert entry.version == 3
    # Options should not have scan_interval if it wasn't in data
    assert CONF_SCAN_INTERVAL not in entry.options
    # But v3 options should be added
    assert entry.options.get(CONF_ENABLE_REPAIR_NOTIFICATION) == DEFAULT_ENABLE_REPAIR_NOTIFICATION
    assert entry.options.get(CONF_FAILURES_THRESHOLD) == DEFAULT_FAILURES_THRESHOLD
    assert entry.options.get(CONF_RECOVERY_SCRIPT) == DEFAULT_RECOVERY_SCRIPT


async def test_migration_v2_to_v3(
    hass: HomeAssistant,
) -> None:
    """Test migration from v2 to v3 adds new repair notification options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: TEST_NAME,
            CONF_HOST: TEST_HOST,
            CONF_PORT: TEST_PORT,
        },
        options={
            CONF_SCAN_INTERVAL: 120,
        },
        version=2,
    )
    entry.add_to_hass(hass)

    result = await async_migrate_entry(hass, entry)

    assert result is True
    assert entry.version == 3
    # Existing options should be preserved
    assert entry.options.get(CONF_SCAN_INTERVAL) == 120
    # v3 adds new repair notification options with defaults
    assert entry.options.get(CONF_ENABLE_REPAIR_NOTIFICATION) == DEFAULT_ENABLE_REPAIR_NOTIFICATION
    assert entry.options.get(CONF_FAILURES_THRESHOLD) == DEFAULT_FAILURES_THRESHOLD
    assert entry.options.get(CONF_RECOVERY_SCRIPT) == DEFAULT_RECOVERY_SCRIPT


# =============================================================================
# TestDeviceRegistry - Tests for async_update_device_registry
# =============================================================================
class TestDeviceRegistry:
    """Tests for device registry functions."""

    async def test_async_update_device_registry_creates_device(
        self,
        hass: HomeAssistant,
        mock_api_data: dict,
    ) -> None:
        """Test that async_update_device_registry creates a device in the registry."""
        # Create a mock coordinator with mock API data
        mock_api = MagicMock()
        mock_api.data = mock_api_data

        mock_coordinator = MagicMock()
        mock_coordinator.api = mock_api

        # Create config entry with runtime data
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: TEST_NAME,
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
            },
            options={
                CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL,
            },
        )
        entry.add_to_hass(hass)
        entry.runtime_data = RuntimeData(coordinator=mock_coordinator)

        # Call the function
        async_update_device_registry(hass, entry)

        # Verify device was created in registry
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, mock_api_data["sn"])})

        assert device is not None
        assert device.name == TEST_NAME
        assert device.manufacturer == mock_api_data["manufact"]
        assert device.model == mock_api_data["model"]
        assert device.sw_version == mock_api_data["swver"]
        assert device.hw_version == mock_api_data["hwver"]
        assert device.serial_number == mock_api_data["sn"]

    async def test_async_update_device_registry_with_all_data(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test device registry creation with complete device information."""
        # Create API data with all fields populated
        api_data = {
            "sn": "SN123456789",
            "manufact": "4-noks",
            "model": "Elios4you Pro",
            "swver": "2.5.1",
            "hwver": "3.0",
        }

        mock_api = MagicMock()
        mock_api.data = api_data

        mock_coordinator = MagicMock()
        mock_coordinator.api = mock_api

        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: "My Solar Monitor",
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
            },
            options={},
        )
        entry.add_to_hass(hass)
        entry.runtime_data = RuntimeData(coordinator=mock_coordinator)

        # Call the function
        async_update_device_registry(hass, entry)

        # Verify device was created with all expected data
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, "SN123456789")})

        assert device is not None
        assert device.name == "My Solar Monitor"
        assert device.manufacturer == "4-noks"
        assert device.model == "Elios4you Pro"
        assert device.sw_version == "2.5.1"
        assert device.hw_version == "3.0"
        assert device.serial_number == "SN123456789"


# =============================================================================
# TestRemoveDevice - Tests for async_remove_config_entry_device
# =============================================================================
class TestRemoveDevice:
    """Tests for device removal function."""

    async def test_async_remove_config_entry_device_denies_domain_device(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test that removing a device with DOMAIN identifier is denied."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: TEST_NAME,
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
            },
            options={},
        )
        entry.add_to_hass(hass)

        # Create a mock DeviceEntry with DOMAIN in identifiers
        mock_device = MagicMock(spec=DeviceEntry)
        mock_device.identifiers = {(DOMAIN, "E4U123456789")}

        # Call the function - should return False (deny removal)
        result = await async_remove_config_entry_device(hass, entry, mock_device)

        assert result is False

    async def test_async_remove_config_entry_device_allows_other_device(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test that removing a device without DOMAIN identifier is allowed."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: TEST_NAME,
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
            },
            options={},
        )
        entry.add_to_hass(hass)

        # Create a mock DeviceEntry with a different domain in identifiers
        mock_device = MagicMock(spec=DeviceEntry)
        mock_device.identifiers = {("other_domain", "some_id")}

        # Call the function - should return True (allow removal)
        result = await async_remove_config_entry_device(hass, entry, mock_device)

        assert result is True

    async def test_async_remove_config_entry_device_empty_identifiers(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test that removing a device with empty identifiers is allowed."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: TEST_NAME,
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
            },
            options={},
        )
        entry.add_to_hass(hass)

        # Create a mock DeviceEntry with empty identifiers
        mock_device = MagicMock(spec=DeviceEntry)
        mock_device.identifiers = set()

        # Call the function - should return True (allow removal)
        result = await async_remove_config_entry_device(hass, entry, mock_device)

        assert result is True


# =============================================================================
# TestUnloadEntry - Tests for async_unload_entry without platform loading
# =============================================================================
class TestUnloadEntry:
    """Tests for unload entry function without requiring platform loading."""

    async def test_async_unload_entry_success_closes_api(
        self,
        hass: HomeAssistant,
        mock_api_data: dict,
    ) -> None:
        """Test that successful unload closes the API connection."""
        # Create mock API with async close method
        mock_api = MagicMock()
        mock_api.data = mock_api_data
        mock_api.close = AsyncMock()

        mock_coordinator = MagicMock()
        mock_coordinator.api = mock_api

        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: TEST_NAME,
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
            },
            options={
                CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL,
            },
        )
        entry.add_to_hass(hass)
        entry.runtime_data = RuntimeData(coordinator=mock_coordinator)

        # Mock async_unload_platforms to return True (success)
        mock_unload = AsyncMock(return_value=True)
        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            mock_unload,
        ):
            result = await async_unload_entry(hass, entry)

        # Verify unload was successful
        assert result is True
        mock_unload.assert_called_once()
        # Verify API close was called
        mock_api.close.assert_called_once()

    async def test_async_unload_entry_failure_skips_cleanup(
        self,
        hass: HomeAssistant,
        mock_api_data: dict,
    ) -> None:
        """Test that failed unload skips API cleanup."""
        # Create mock API
        mock_api = MagicMock()
        mock_api.data = mock_api_data
        mock_api.close = AsyncMock()

        mock_coordinator = MagicMock()
        mock_coordinator.api = mock_api

        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: TEST_NAME,
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
            },
            options={
                CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL,
            },
        )
        entry.add_to_hass(hass)
        entry.runtime_data = RuntimeData(coordinator=mock_coordinator)

        # Mock async_unload_platforms to return False (failure)
        mock_unload = AsyncMock(return_value=False)
        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            mock_unload,
        ):
            result = await async_unload_entry(hass, entry)

        # Verify unload failed
        assert result is False
        mock_unload.assert_called_once()
        # Verify API close was NOT called (cleanup skipped)
        mock_api.close.assert_not_called()


# =============================================================================
# TestMigration - Additional migration tests
# =============================================================================
class TestMigration:
    """Additional tests for config entry migration."""

    async def test_migration_v3_no_change(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test that v3 entries are not modified (already at current version)."""
        original_data = {
            CONF_NAME: TEST_NAME,
            CONF_HOST: TEST_HOST,
            CONF_PORT: TEST_PORT,
        }
        original_options = {
            CONF_SCAN_INTERVAL: 120,
            CONF_ENABLE_REPAIR_NOTIFICATION: True,
            CONF_FAILURES_THRESHOLD: 5,
            CONF_RECOVERY_SCRIPT: "script.my_recovery",
        }

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=original_data.copy(),
            options=original_options.copy(),
            version=3,  # Already at v3
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        # Should succeed without modifying anything
        assert result is True
        assert entry.version == 3
        # Data and options should remain unchanged
        assert entry.data == original_data
        assert entry.options == original_options

    async def test_migration_v1_preserves_existing_options(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test migration from v1 preserves existing options while moving scan_interval."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: TEST_NAME,
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
                CONF_SCAN_INTERVAL: 90,
            },
            options={
                "some_other_option": "value",  # Existing option
            },
            version=1,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 3
        # scan_interval should be moved to options
        assert CONF_SCAN_INTERVAL not in entry.data
        assert entry.options.get(CONF_SCAN_INTERVAL) == 90
        # Existing options should be preserved
        assert entry.options.get("some_other_option") == "value"
        # v3 options should be added
        assert (
            entry.options.get(CONF_ENABLE_REPAIR_NOTIFICATION) == DEFAULT_ENABLE_REPAIR_NOTIFICATION
        )

    async def test_migration_rejects_future_version(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test that migration returns False for future versions (downgrade protection)."""
        # Test with a higher version - should be rejected
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: TEST_NAME,
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
            },
            options={},
            version=99,  # Future version
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        # Should return False for versions higher than current (downgrade protection)
        assert result is False

    async def test_migration_accepts_current_version(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Test that migration returns True for current version."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_NAME: TEST_NAME,
                CONF_HOST: TEST_HOST,
                CONF_PORT: TEST_PORT,
            },
            options={
                CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL,
                CONF_ENABLE_REPAIR_NOTIFICATION: True,
                CONF_FAILURES_THRESHOLD: 3,
                CONF_RECOVERY_SCRIPT: "",
            },
            version=3,  # Current version
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        # Should return True for current version
        assert result is True


class TestAsyncSetup:
    """Tests for async_setup (domain-level service registration)."""

    @pytest.mark.asyncio
    async def test_async_setup_registers_services(self, hass: HomeAssistant) -> None:
        """Test that async_setup registers the three schedule services."""
        with patch.object(hass.services, "async_register") as mock_register:
            result = await async_setup(hass, {})

        assert result is True
        service_names = [call.args[1] for call in mock_register.call_args_list]
        assert "get_schedule" in service_names
        assert "set_schedule" in service_names
        assert "set_schedule_range" in service_names


class TestAsyncApplyPrEntityState:
    """Tests for _async_apply_pr_entity_state."""

    def _make_entry_with_coordinator(self, hass, power_reducer_option):
        """Helper: create a config entry with runtime_data and a coordinator."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_NAME: TEST_NAME, CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT},
            options={
                CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL,
                **(
                    {CONF_POWER_REDUCER: power_reducer_option}
                    if power_reducer_option is not None
                    else {}
                ),
            },
        )
        entry.add_to_hass(hass)
        mock_coordinator = MagicMock()
        mock_coordinator.api = MagicMock()
        mock_coordinator.api.data = {
            "sn": TEST_SERIAL_NUMBER,
            "manufact": "4-noks",
            "model": "Elios4you",
            "swver": "1.0",
            "hwver": "2.0",
        }
        entry.runtime_data = RuntimeData(coordinator=mock_coordinator)
        return entry

    @pytest.mark.asyncio
    async def test_option_none_leaves_entities_untouched(self, hass: HomeAssistant) -> None:
        """Test that when power_reducer option is not set, nothing changes."""
        entry = self._make_entry_with_coordinator(hass, power_reducer_option=None)

        ent_reg = er.async_get(hass)
        # Calling should not raise and should not modify any entity
        _async_apply_pr_entity_state(hass, entry)
        # No PR entities are registered so nothing to check, just confirm no crash
        entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        assert entries == []

    @pytest.mark.asyncio
    async def test_option_true_enables_integration_disabled_entities(
        self, hass: HomeAssistant
    ) -> None:
        """Test that power_reducer=True enables integration-disabled PR entities."""
        entry = self._make_entry_with_coordinator(hass, power_reducer_option=True)
        ent_reg = er.async_get(hass)

        # Register a fake PR entity that is integration-disabled
        pr_key = next(iter(PR_ENTITY_KEYS))
        fake_entity = ent_reg.async_get_or_create(
            domain="sensor",
            platform=DOMAIN,
            unique_id=f"{DOMAIN}_{TEST_SERIAL_NUMBER}_{pr_key}",
            config_entry=entry,
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        )

        _async_apply_pr_entity_state(hass, entry)

        updated = ent_reg.async_get(fake_entity.entity_id)
        assert updated.disabled_by is None

    @pytest.mark.asyncio
    async def test_option_false_disables_enabled_pr_entities(self, hass: HomeAssistant) -> None:
        """Test that power_reducer=False disables enabled PR entities."""
        entry = self._make_entry_with_coordinator(hass, power_reducer_option=False)
        ent_reg = er.async_get(hass)

        pr_key = next(iter(PR_ENTITY_KEYS))
        fake_entity = ent_reg.async_get_or_create(
            domain="sensor",
            platform=DOMAIN,
            unique_id=f"{DOMAIN}_{TEST_SERIAL_NUMBER}_{pr_key}",
            config_entry=entry,
        )

        _async_apply_pr_entity_state(hass, entry)

        updated = ent_reg.async_get(fake_entity.entity_id)
        assert updated.disabled_by == er.RegistryEntryDisabler.INTEGRATION

    @pytest.mark.asyncio
    async def test_option_true_does_not_re_enable_user_disabled_entities(
        self, hass: HomeAssistant
    ) -> None:
        """Test that power_reducer=True only re-enables integration-disabled, not user-disabled."""
        entry = self._make_entry_with_coordinator(hass, power_reducer_option=True)
        ent_reg = er.async_get(hass)

        pr_key = next(iter(PR_ENTITY_KEYS))
        fake_entity = ent_reg.async_get_or_create(
            domain="sensor",
            platform=DOMAIN,
            unique_id=f"{DOMAIN}_{TEST_SERIAL_NUMBER}_{pr_key}",
            config_entry=entry,
            disabled_by=er.RegistryEntryDisabler.USER,
        )

        _async_apply_pr_entity_state(hass, entry)

        # User-disabled entity should remain user-disabled
        updated = ent_reg.async_get(fake_entity.entity_id)
        assert updated.disabled_by == er.RegistryEntryDisabler.USER


class TestScheduleServices:
    """Tests for the schedule service handlers registered by _register_schedule_services."""

    def _setup_hass_services(self, hass):
        """Register schedule services on the test hass instance."""
        _register_schedule_services(hass)

    def _make_config_entry_with_api(self, hass, api_mock=None):
        """Create a config entry with a mock coordinator/API attached as runtime_data."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_NAME: TEST_NAME, CONF_HOST: TEST_HOST, CONF_PORT: TEST_PORT},
            options={CONF_SCAN_INTERVAL: TEST_SCAN_INTERVAL},
        )
        entry.add_to_hass(hass)
        if api_mock is None:
            api_mock = MagicMock()
        coordinator = MagicMock()
        coordinator.api = api_mock
        entry.runtime_data = RuntimeData(coordinator=coordinator)
        return entry, coordinator

    # ── get_schedule ─────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_schedule_success(self, hass: HomeAssistant) -> None:
        """Test get_schedule returns structured schedule data."""
        self._setup_hass_services(hass)
        slots = ["auto"] * 48
        api_mock = MagicMock()
        api_mock.async_read_schedule = AsyncMock(return_value=slots)
        entry, _ = self._make_config_entry_with_api(hass, api_mock)

        # Call service directly via hass
        result = await hass.services.async_call(
            DOMAIN,
            "get_schedule",
            {"config_entry_id": entry.entry_id, "day": 1},
            return_response=True,
            blocking=True,
        )

        assert result["day"] == "monday"
        assert len(result["slots"]) == 48
        assert result["slots"][0]["time"] == "00:00"
        assert result["slots"][1]["time"] == "00:30"
        assert result["slots"][47]["time"] == "23:30"

    @pytest.mark.asyncio
    async def test_get_schedule_invalid_config_entry_raises(self, hass: HomeAssistant) -> None:
        """Test get_schedule raises ServiceValidationError for unknown entry_id."""
        self._setup_hass_services(hass)

        with pytest.raises((ServiceValidationError, Exception)):
            await hass.services.async_call(
                DOMAIN,
                "get_schedule",
                {"config_entry_id": "nonexistent-id", "day": 0},
                return_response=True,
                blocking=True,
            )

    @pytest.mark.asyncio
    async def test_get_schedule_read_failure_raises(self, hass: HomeAssistant) -> None:
        """Test get_schedule raises ServiceValidationError when device read fails."""
        self._setup_hass_services(hass)
        api_mock = MagicMock()
        api_mock.async_read_schedule = AsyncMock(return_value=None)
        entry, _ = self._make_config_entry_with_api(hass, api_mock)

        with pytest.raises((ServiceValidationError, Exception)):
            await hass.services.async_call(
                DOMAIN,
                "get_schedule",
                {"config_entry_id": entry.entry_id, "day": 0},
                return_response=True,
                blocking=True,
            )

    # ── set_schedule ─────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_set_schedule_success(self, hass: HomeAssistant) -> None:
        """Test set_schedule writes the schedule to device."""
        self._setup_hass_services(hass)
        api_mock = MagicMock()
        api_mock.async_write_schedule = AsyncMock(return_value=True)
        entry, _ = self._make_config_entry_with_api(hass, api_mock)
        slots = ["auto"] * 48

        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {"config_entry_id": entry.entry_id, "day": 0, "slots": slots},
            blocking=True,
        )

        api_mock.async_write_schedule.assert_called_once_with(0, slots)

    @pytest.mark.asyncio
    async def test_set_schedule_write_failure_raises(self, hass: HomeAssistant) -> None:
        """Test set_schedule raises when device write fails."""
        self._setup_hass_services(hass)
        api_mock = MagicMock()
        api_mock.async_write_schedule = AsyncMock(return_value=False)
        entry, _ = self._make_config_entry_with_api(hass, api_mock)

        with pytest.raises((ServiceValidationError, Exception)):
            await hass.services.async_call(
                DOMAIN,
                "set_schedule",
                {"config_entry_id": entry.entry_id, "day": 0, "slots": ["auto"] * 48},
                blocking=True,
            )

    # ── set_schedule_range ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_set_schedule_range_success(self, hass: HomeAssistant) -> None:
        """Test set_schedule_range patches a time range and writes back."""
        self._setup_hass_services(hass)
        initial_slots = ["auto"] * 48
        api_mock = MagicMock()
        api_mock.async_read_schedule = AsyncMock(return_value=list(initial_slots))
        api_mock.async_write_schedule = AsyncMock(return_value=True)
        entry, _ = self._make_config_entry_with_api(hass, api_mock)

        await hass.services.async_call(
            DOMAIN,
            "set_schedule_range",
            {
                "config_entry_id": entry.entry_id,
                "day": 1,
                "start_time": "06:00",
                "end_time": "08:00",
                "mode": "boost",
            },
            blocking=True,
        )

        # Slots 12-15 (06:00–07:30) should be "boost"; 16+ stay "auto"
        written_slots = api_mock.async_write_schedule.call_args.args[1]
        assert written_slots[12] == "boost"
        assert written_slots[15] == "boost"
        assert written_slots[16] == "auto"

    @pytest.mark.asyncio
    async def test_set_schedule_range_read_failure_raises(self, hass: HomeAssistant) -> None:
        """Test set_schedule_range raises when reading current schedule fails."""
        self._setup_hass_services(hass)
        api_mock = MagicMock()
        api_mock.async_read_schedule = AsyncMock(return_value=None)
        entry, _ = self._make_config_entry_with_api(hass, api_mock)

        with pytest.raises((ServiceValidationError, Exception)):
            await hass.services.async_call(
                DOMAIN,
                "set_schedule_range",
                {
                    "config_entry_id": entry.entry_id,
                    "day": 0,
                    "start_time": "06:00",
                    "end_time": "08:00",
                    "mode": "boost",
                },
                blocking=True,
            )

    @pytest.mark.asyncio
    async def test_set_schedule_range_write_failure_raises(self, hass: HomeAssistant) -> None:
        """Test set_schedule_range raises when writing updated schedule fails."""
        self._setup_hass_services(hass)
        api_mock = MagicMock()
        api_mock.async_read_schedule = AsyncMock(return_value=["auto"] * 48)
        api_mock.async_write_schedule = AsyncMock(return_value=False)
        entry, _ = self._make_config_entry_with_api(hass, api_mock)

        with pytest.raises((ServiceValidationError, Exception)):
            await hass.services.async_call(
                DOMAIN,
                "set_schedule_range",
                {
                    "config_entry_id": entry.entry_id,
                    "day": 0,
                    "start_time": "06:00",
                    "end_time": "08:00",
                    "mode": "off",
                },
                blocking=True,
            )
