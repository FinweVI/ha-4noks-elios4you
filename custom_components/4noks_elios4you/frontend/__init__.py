"""Frontend registration for 4-noks Elios4You scheduler card.

Handles three responsibilities:
1. Serve the card JS file as a static HTTP path (all Lovelace modes).
2. Auto-register the resource in Lovelace storage mode.
3. Raise a repair issue in YAML mode so the user gets an actionable notice.
4. Expose a WebSocket command so the card can detect backend version mismatches.
"""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from ..const import DOMAIN, VERSION
from ..helpers import log_debug

_LOGGER = logging.getLogger(__name__)

_CARD_FILENAME = "elios4you-scheduler-card.js"
_LOVELACE_YAML_ISSUE_ID = "lovelace_yaml_resource"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the static HTTP path and attempt Lovelace resource registration.

    Must be called after HA has fully started so the lovelace component data is
    available. Called from async_setup via an EVENT_HOMEASSISTANT_STARTED listener.
    """
    resource_url = f"/{DOMAIN}/{_CARD_FILENAME}?v={VERSION}"

    # ── 1. Static HTTP path (always, independent of Lovelace mode) ────────────
    # Serves the JS file at https://<ha>/4noks_elios4you/elios4you-scheduler-card.js
    try:
        # Register only the specific JS file (not the whole directory) so that
        # __pycache__ bytecode and __init__.py are not reachable over HTTP.
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    f"/{DOMAIN}/{_CARD_FILENAME}",
                    Path(__file__).parent / _CARD_FILENAME,
                    cache_headers=False,
                )
            ]
        )
        log_debug(
            _LOGGER,
            "async_register_frontend",
            "Static path registered",
            url=f"/{DOMAIN}/{_CARD_FILENAME}",
        )
    except RuntimeError:
        # "A path was already registered" — harmless, the file is already served.
        # This can happen on config-entry reload within the same HA session.
        log_debug(_LOGGER, "async_register_frontend", "Static path already registered, skipping")
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("(async_register_frontend): Failed to register static path: %s", err)
        return

    # ── 2. Lovelace resource auto-registration (storage mode only) ─────────────
    registered = await _try_register_lovelace_resource(hass, resource_url)

    if registered:
        # Clear any lingering YAML-mode repair issue (e.g. user switched modes)
        async_delete_issue(hass, DOMAIN, _LOVELACE_YAML_ISSUE_ID)
    else:
        # YAML mode or resource store unavailable — surface a repair with instructions
        log_debug(
            _LOGGER,
            "async_register_frontend",
            "Cannot auto-register Lovelace resource, raising repair issue",
        )
        async_create_issue(
            hass,
            DOMAIN,
            _LOVELACE_YAML_ISSUE_ID,
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key=_LOVELACE_YAML_ISSUE_ID,
            translation_placeholders={"resource_url": resource_url},
        )


async def _try_register_lovelace_resource(hass: HomeAssistant, resource_url: str) -> bool:
    """Attempt to add or update the card in the Lovelace resource store.

    Returns True if successful (storage mode), False if YAML mode or unavailable.
    Errors are logged as warnings and return False so the caller can fall back to
    raising a repair issue instead of crashing the integration setup.
    """
    try:
        # TODO: hass.data["lovelace"] is an internal HA implementation detail, not a public API.
        # Verified against HA 2025.10. In HA 2025.2+ this became a LovelaceData dataclass
        # (previously a plain dict). We access its attributes via getattr() so the code works
        # across both forms. Watch for HA 2026.2 which may further change this structure.
        # Upstream tracking: github.com/home-assistant/core/blob/dev/homeassistant/components/lovelace/__init__.py
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data is None:
            log_debug(_LOGGER, "_try_register_lovelace_resource", "Lovelace data not available")
            return False

        # Pre-2025.2: lovelace_data was a dict with a "default" key.
        # 2025.2+: lovelace_data is the LovelaceData dataclass directly.
        # Both cases handled transparently via getattr below.
        lovelace = (
            lovelace_data.get("default", lovelace_data)
            if isinstance(lovelace_data, dict)
            else lovelace_data
        )

        if getattr(lovelace, "mode", None) == "yaml":
            log_debug(_LOGGER, "_try_register_lovelace_resource", "Lovelace is in YAML mode")
            return False

        resources = getattr(lovelace, "resources", None)
        if resources is None:
            log_debug(
                _LOGGER, "_try_register_lovelace_resource", "No resource store on lovelace object"
            )
            return False

        await resources.async_load()

        base_url = f"/{DOMAIN}/{_CARD_FILENAME}"
        existing = {r["url"].split("?")[0]: r for r in resources.async_items()}

        if base_url in existing:
            if existing[base_url]["url"] != resource_url:
                # Version changed — update the versioned query-string
                await resources.async_update_item(
                    existing[base_url]["id"],
                    {"res_type": "module", "url": resource_url},
                )
                log_debug(
                    _LOGGER,
                    "_try_register_lovelace_resource",
                    "Updated Lovelace resource",
                    url=resource_url,
                )
            else:
                log_debug(
                    _LOGGER,
                    "_try_register_lovelace_resource",
                    "Lovelace resource already up-to-date",
                )
        else:
            await resources.async_create_item({"res_type": "module", "url": resource_url})
            log_debug(
                _LOGGER,
                "_try_register_lovelace_resource",
                "Registered new Lovelace resource",
                url=resource_url,
            )

    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "(async_register_frontend): Unexpected error registering Lovelace resource: %s", err
        )
        return False
    else:
        return True


def async_register_websocket(hass: HomeAssistant) -> None:
    """Register a WebSocket command that returns the current backend version.

    The card calls this on connectedCallback() to detect version mismatches caused
    by stale browser/app caches and shows a 'clear cache & reload' prompt when needed.
    """

    @callback
    @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/lovelace_version"})
    def _ws_lovelace_version(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
    ) -> None:
        """Return integration version for frontend cache-busting."""
        connection.send_result(msg["id"], {"version": VERSION})

    websocket_api.async_register_command(hass, _ws_lovelace_version)
    log_debug(_LOGGER, "async_register_websocket", "WebSocket version command registered")
