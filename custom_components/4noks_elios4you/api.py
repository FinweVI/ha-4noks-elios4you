"""API Platform for 4-noks Elios4You.

https://github.com/alexdelprete/ha-4noks-elios4you
"""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
import logging
import socket
import time
from typing import ClassVar

import telnetlib3

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CLOCK_DRIFT_THRESHOLD,
    COMMAND_RETRY_COUNT,
    COMMAND_RETRY_DELAY,
    CONN_TIMEOUT,
    DEFAULT_BOOST_DURATION,
    DEFAULT_BOOST_LEVEL,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .helpers import log_debug, log_warning

_LOGGER = logging.getLogger(__name__)


class TelnetConnectionError(HomeAssistantError):
    """Exception raised when telnet connection fails."""

    def __init__(self, host: str, port: int, timeout: int, message: str = "") -> None:
        """Initialize the exception."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self.message = message or f"Failed to connect to {host}:{port} (timeout: {timeout}s)"
        super().__init__(self.message)
        self.translation_domain = DOMAIN
        self.translation_key = "telnet_connection_error"
        self.translation_placeholders = {
            "host": host,
            "port": str(port),
            "timeout": str(timeout),
        }


class TelnetCommandError(HomeAssistantError):
    """Exception raised when telnet command fails."""

    def __init__(self, command: str, message: str = "") -> None:
        """Initialize the exception."""
        self.command = command
        self.message = message or f"Command '{command}' failed"
        super().__init__(self.message)
        self.translation_domain = DOMAIN
        self.translation_key = "telnet_command_error"
        self.translation_placeholders = {
            "command": command,
        }


class Elios4YouAPI:
    """Wrapper class for Elios4You telnet communication.

    Uses telnetlib3 for fully async I/O to avoid blocking the Home Assistant event loop.
    """

    # Connection reuse timeout in seconds - reuse connection if last activity within this window
    CONNECTION_REUSE_TIMEOUT: float = 25.0

    def __init__(self, hass: HomeAssistant, name: str, host: str, port: int) -> None:
        """Initialize the Elios4You API Client."""
        self._hass = hass
        self._name = name
        self._host = host
        self._port = port
        self._timeout = CONN_TIMEOUT
        self._sensors: list[str] = []
        self.data: dict[str, int | float | str] = {}

        # Async telnetlib3 reader/writer streams
        # Note: telnetlib3 returns TelnetReaderUnicode/TelnetWriterUnicode
        # which extend asyncio.StreamReader/StreamWriter with telnet protocol handling
        self._reader: telnetlib3.TelnetReaderUnicode | None = None
        self._writer: telnetlib3.TelnetWriterUnicode | None = None

        # Connection pooling: prevent socket exhaustion on embedded device
        self._connection_lock = asyncio.Lock()
        self._last_activity: float = 0.0

        # Initialize Elios4You data structure before first read
        self.data["produced_power"] = None
        self.data["consumed_power"] = None
        self.data["self_consumed_power"] = None
        self.data["bought_power"] = None
        self.data["sold_power"] = None
        self.data["daily_peak"] = None
        self.data["monthly_peak"] = None
        self.data["produced_energy"] = None
        self.data["produced_energy_f1"] = None
        self.data["produced_energy_f2"] = None
        self.data["produced_energy_f3"] = None
        self.data["consumed_energy"] = None
        self.data["consumed_energy_f1"] = None
        self.data["consumed_energy_f2"] = None
        self.data["consumed_energy_f3"] = None
        self.data["self_consumed_energy"] = None
        self.data["self_consumed_energy_f1"] = None
        self.data["self_consumed_energy_f2"] = None
        self.data["self_consumed_energy_f3"] = None
        self.data["bought_energy"] = None
        self.data["bought_energy_f1"] = None
        self.data["bought_energy_f2"] = None
        self.data["bought_energy_f3"] = None
        self.data["sold_energy"] = None
        self.data["sold_energy_f1"] = None
        self.data["sold_energy_f2"] = None
        self.data["sold_energy_f3"] = None
        self.data["alarm_1"] = None
        self.data["alarm_2"] = None
        self.data["power_alarm"] = None
        self.data["relay_state"] = None
        self.data["pwm_mode"] = None
        self.data["pr_ssv"] = None
        self.data["rel_ssv"] = None
        self.data["rel_mode"] = None
        self.data["rel_warning"] = None
        self.data["rcap"] = None
        self.data["utc_time"] = ""
        self.data["fwtop"] = ""
        self.data["fwbtm"] = ""
        self.data["sn"] = ""
        self.data["hwver"] = ""
        self.data["btver"] = ""
        self.data["hw_wifi"] = ""
        self.data["s2w_app_version"] = ""
        self.data["s2w_geps_version"] = ""
        self.data["s2w_wlan_version"] = ""
        # custom fields to reuse code structure
        self.data["manufact"] = MANUFACTURER
        self.data["model"] = MODEL
        # Power Reducer data keys (populated from @dat)
        self.data["reducer_power"] = 0  # 0-10000 (basis points, 10000=100%)
        self.data["boost_active"] = 0  # 0 or 1
        self.data["boost_power"] = 0  # 0-10000
        self.data["boost_delay"] = 0  # seconds (total boost duration configured)
        self.data["boost_remaining"] = 0  # seconds remaining (0 when inactive)
        self.data["pr_load_warning"] = 0  # 0 or 1
        self.data["pr_mode"] = "auto"  # computed: "auto" or "boost"
        # PAR parameters (populated once per session, reset via reset_par_cache)
        self.data["spf_ldw"] = 0  # Power Reducer load power (watts)
        self.data["spf_spw"] = 0  # Power Reducer surplus threshold (watts)
        # Local-only: boost parameters (not written to device)
        self.data["boost_duration"] = DEFAULT_BOOST_DURATION
        self.data["boost_level"] = DEFAULT_BOOST_LEVEL  # percent (10-100)
        # PAR caching: fetch once per connection session
        self._par_fetched: bool = False
        # Hardware version parsed fields (populated on first connect via handshake)
        self.data["hwver_raw"] = ""  # 12-char hex from @hwr
        self.data["has_rs485"] = 0  # bool: RS485 interface present
        self.data["has_pr_hw"] = 0  # bool: PowerReducer-compatible hardware
        self.data["vendor_id"] = ""  # 2-char hex (vendor ID byte)
        self.data["mc_type"] = ""  # 2-char hex (MC type byte)
        # Clock management
        self.data["device_clock_utc"] = None  # datetime (UTC) once first clock read succeeds
        self.data["clock_drift"] = 0  # seconds, positive = device ahead

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._name

    @property
    def host(self) -> str:
        """Return the device name."""
        return self._host

    async def close(self) -> None:
        """Close the telnet connection."""
        await self._safe_close()

    def _is_connection_valid(self) -> bool:
        """Check if existing connection can be reused.

        Returns True if:
        - Writer stream exists and is open
        - Last activity was within CONNECTION_REUSE_TIMEOUT seconds
        """
        if self._writer is None:
            return False
        # Check if connection is closing - telnetlib3 writer may or may not have is_closing()
        # Fall back to checking the underlying transport
        try:
            if hasattr(self._writer, "is_closing") and self._writer.is_closing():
                return False
            # Also check transport if available
            transport = self._writer.get_extra_info("transport")
            if transport is not None and transport.is_closing():
                return False
        except (AttributeError, OSError):
            # If we can't determine state, assume connection is invalid
            return False

        if time.time() - self._last_activity > self.CONNECTION_REUSE_TIMEOUT:
            log_debug(
                _LOGGER,
                "_is_connection_valid",
                "Connection expired, will reconnect",
                idle_seconds=round(time.time() - self._last_activity, 1),
            )
            return False
        return True

    async def _safe_close(self) -> None:
        """Safely close connection with proper cleanup.

        This method:
        - Closes the writer stream gracefully
        - Waits for connection to fully close
        - Resets connection state
        """
        if self._writer is not None:
            with suppress(Exception):
                self._writer.close()
                await self._writer.wait_closed()
            self._writer = None
            self._reader = None
            self._last_activity = 0.0
            log_debug(_LOGGER, "_safe_close", "Connection closed and cleaned up")
        else:
            log_debug(_LOGGER, "_safe_close", "No connection to close")

    async def _ensure_connected(self) -> None:
        """Open connection only if needed, reusing existing connection if valid.

        This method implements connection pooling to prevent socket exhaustion
        on the embedded Elios4You device.

        Raises:
            TelnetConnectionError: If connection cannot be established.
        """
        if self._is_connection_valid():
            log_debug(
                _LOGGER,
                "_ensure_connected",
                "Reusing existing connection",
                idle_seconds=round(time.time() - self._last_activity, 1),
            )
            self._last_activity = time.time()
            return

        # Close any stale connection before opening new one
        await self._safe_close()

        try:
            log_debug(
                _LOGGER,
                "_ensure_connected",
                "Opening new connection",
                host=self._host,
                port=self._port,
            )
            # telnetlib3.open_connection parameters:
            # - encoding: 'utf-8' for unicode string handling (default is 'utf8')
            # - encoding_errors: 'replace' to handle invalid chars gracefully
            # - connect_minwait: Minimum wait for telnet option negotiation (default 2.0s)
            # - connect_maxwait: Maximum wait for negotiation (default 3.0s)
            # We set low values since Elios4You doesn't use telnet option negotiation
            self._reader, self._writer = await asyncio.wait_for(  # type: ignore[assignment]
                telnetlib3.open_connection(
                    host=self._host,
                    port=self._port,
                    encoding="utf-8",
                    encoding_errors="replace",
                    connect_minwait=0.1,  # Don't wait for telnet negotiation
                    connect_maxwait=0.5,  # Quick timeout on negotiation
                ),
                timeout=self._timeout,
            )
            try:
                await self._perform_handshake()
            except TelnetConnectionError:
                await self._safe_close()
                raise
            self._last_activity = time.time()
            log_debug(_LOGGER, "_ensure_connected", "Connection established")
        except (TimeoutError, OSError) as err:
            log_debug(
                _LOGGER,
                "_ensure_connected",
                "Connection failed",
                error=str(err),
            )
            raise TelnetConnectionError(
                self._host, self._port, self._timeout, f"Connection failed: {err}"
            ) from err

    async def _async_read_until(
        self,
        separator: str,
        timeout: float,
    ) -> str:
        """Async read until separator found or timeout.

        telnetlib3 provides stream-based I/O without built-in read_until,
        so we implement our own async version.

        Note: telnetlib3 works with strings (not bytes) - it handles encoding internally.

        Args:
            separator: String sequence to wait for (e.g., "ready...")
            timeout: Maximum seconds to wait

        Returns:
            Buffer containing data up to and including separator,
            or partial data if timeout/EOF occurs.
        """
        buffer = ""
        loop = asyncio.get_running_loop()
        end_time = loop.time() + timeout

        while separator not in buffer:
            remaining = end_time - loop.time()
            if remaining <= 0:
                log_debug(
                    _LOGGER,
                    "_async_read_until",
                    "Timeout waiting for separator",
                    buffer_len=len(buffer),
                )
                return buffer  # Timeout - return partial

            try:
                if self._reader is None:
                    return buffer
                chunk = await asyncio.wait_for(
                    self._reader.read(1024),
                    timeout=remaining,
                )
                if not chunk:
                    log_debug(
                        _LOGGER,
                        "_async_read_until",
                        "EOF received",
                        buffer_len=len(buffer),
                    )
                    return buffer  # EOF
                buffer += chunk
            except TimeoutError:
                log_debug(
                    _LOGGER,
                    "_async_read_until",
                    "asyncio.TimeoutError during read",
                    buffer_len=len(buffer),
                )
                return buffer

        return buffer

    async def _async_send_command(self, cmd: str) -> dict | None:
        """Send structured command and return parsed key-value dict.

        Delegates the low-level send+read to _async_send_raw, then parses
        the structured response for @dat, @sta, @inf, @rel, @hwr commands.

        Args:
            cmd: Command to send (e.g., "@dat", "@sta", "@inf", "@rel")

        Returns:
            Parsed response dict or None if failed
        """
        cmd_main = cmd[0:4].lower()
        log_debug(_LOGGER, "_async_send_command", "Sending command", cmd=cmd)

        # Delegate low-level send+read to _async_send_raw (all-lowercase for structured cmds)
        raw = await self._async_send_raw(cmd.lower())
        if raw is None:
            log_debug(_LOGGER, "_async_send_command", "Silent timeout or connection error")
            return None

        # Parse structured response (raw is already stripped of "ready...")
        output: dict[str, str] = {}
        lines = raw.splitlines()

        # Find where data lines start: skip the command echo if present
        lines_start = 0
        for i, line in enumerate(lines):
            if line.strip().lower() in ("@dat", "@sta", "@inf", "@rel", "@hwr"):
                lines_start = i + 1
                break

        for line in lines[lines_start:]:
            line = line.strip()
            if not line:
                continue  # blank lines are expected between sections
            try:
                if cmd_main in ("@inf", "@rel", "@hwr"):
                    key, value = line.split("=", 1)
                else:
                    key, value = line.split(";")[1:3]
                output[key.lower().replace(" ", "_")] = value.strip()
            except (ValueError, IndexError):
                # Non-empty line that doesn't match expected format → response is corrupt.
                # Return None so the coordinator keeps existing values and retries next cycle.
                log_debug(
                    _LOGGER,
                    "_async_send_command",
                    "Malformed response line, discarding entire response",
                    line=line,
                )
                return None

        log_debug(
            _LOGGER,
            "_async_send_command",
            "Success",
            output_keys=list(output.keys()),
        )
        return output

    async def _require_data(self, cmd: str) -> dict:
        """Get data with retry, raising TelnetCommandError if it fails.

        Args:
            cmd: Telnet command to execute (@dat, @sta, @inf)

        Returns:
            Parsed response dict

        Raises:
            TelnetCommandError: If command fails after retries
        """
        result = await self._get_data_with_retry(cmd)
        if result is None:
            await self._safe_close()
            raise TelnetCommandError(cmd, f"Failed to retrieve {cmd} data")
        return result

    async def _get_data_with_retry(
        self,
        cmd: str,
        max_retries: int = COMMAND_RETRY_COUNT,
    ) -> dict | None:
        """Execute telnet command with retry logic for transient failures.

        If command fails (returns None due to silent timeout or error),
        closes connection, reconnects, and retries up to max_retries times.

        Args:
            cmd: Telnet command to execute (@dat, @sta, @inf, @rel)
            max_retries: Maximum number of retry attempts

        Returns:
            Parsed response dict or None if all attempts fail
        """
        for attempt in range(max_retries + 1):
            result = await self._async_send_command(cmd)
            if result is not None:
                return result

            if attempt < max_retries:
                log_debug(
                    _LOGGER,
                    "_get_data_with_retry",
                    "Command failed, retrying",
                    cmd=cmd,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                )
                await asyncio.sleep(COMMAND_RETRY_DELAY)
                # Close stale connection and reconnect for retry
                await self._safe_close()
                await self._ensure_connected()

        return None

    def check_port(self) -> bool:
        """Check if port is available.

        Note: This method is kept for backwards compatibility with tests.
        The main code now uses _ensure_connected() for connection management.
        WARNING: This is a BLOCKING synchronous call. Do NOT invoke from an async context.
        """
        sock_timeout = 3.0
        log_debug(
            _LOGGER,
            "check_port",
            "Opening socket",
            host=self._host,
            port=self._port,
            timeout=sock_timeout,
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Use socket-specific timeout instead of global (prevents thread-safety issues)
            sock.settimeout(sock_timeout)
            sock_res = sock.connect_ex((self._host, self._port))
            # True if open, False if not
            is_open = sock_res == 0
            if is_open:
                with suppress(Exception):
                    sock.shutdown(socket.SHUT_RDWR)
                log_debug(
                    _LOGGER,
                    "check_port",
                    "Port open",
                    host=self._host,
                    port=self._port,
                )
            else:
                log_debug(
                    _LOGGER,
                    "check_port",
                    "Port not available",
                    host=self._host,
                    port=self._port,
                    error=sock_res,
                )
            return is_open
        finally:
            sock.close()

    def _parse_hwver(self, hwver: str) -> None:
        """Decode 12-char HWVER hex string and populate data fields.

        HWVER format (each pair = 1 byte, hex):
          [0:2]  mc_type    "00"=128K MC, "01"=256K/RedCap MC
          [6:8]  rs485_byte bit0 = RS485 interface present
          [8:10] vendor_id  "0C"=Reverberi EDI
          [11]   pr_hw bit  "1"=PowerReducer-compatible hardware
        """
        if len(hwver) < 12:
            return
        self.data["hwver_raw"] = hwver
        self.data["mc_type"] = hwver[0:2]
        rs485_byte = int(hwver[6:8], 16)
        self.data["has_rs485"] = rs485_byte & 1
        self.data["vendor_id"] = hwver[8:10]
        self.data["has_pr_hw"] = 1 if hwver[11] == "1" else 0

    async def _perform_handshake(self) -> None:
        """Send @hwr and validate HWVER= in response to confirm device identity.

        Raises:
            TelnetConnectionError: If response does not contain HWVER=.
        """
        raw = await self._async_send_raw("@hwr")
        if raw is None or "HWVER=" not in raw.upper():
            raise TelnetConnectionError(
                self._host,
                self._port,
                self._timeout,
                "Handshake failed: no HWVER in response",
            )
        for line in raw.splitlines():
            if line.upper().startswith("HWVER="):
                hwver_val = line.split("=", 1)[1].strip()
                self._parse_hwver(hwver_val)
                break
        if len(self.data.get("hwver_raw", "")) < 12:
            raise TelnetConnectionError(
                self._host,
                self._port,
                self._timeout,
                f"Handshake failed: HWVER value too short: {self.data.get('hwver_raw')!r}",
            )
        log_debug(
            _LOGGER,
            "_perform_handshake",
            "Handshake OK",
            hwver_raw=self.data["hwver_raw"],
        )

    # PAR parameters accepted by the device — used as an allowlist in read/write methods
    _ALLOWED_PAR_PARAMS: frozenset[str] = frozenset({"SPF_LDW", "SPF_SPW"})

    # @PRS slot value encoding (confirmed from 4noks app telnet captures):
    #   0 = OFF (forced stop)   1 = BOOST (forced heat)   2 = AUTO (solar tracking)
    # _SLOT_MODES is the canonical read map; the write map is its inverse.
    _SLOT_MODES: ClassVar[dict[str, str]] = {"0": "off", "1": "boost", "2": "auto"}
    _SLOT_WRITE: ClassVar[dict[str, str]] = {mode: code for code, mode in _SLOT_MODES.items()}

    async def _async_send_raw(self, cmd: str) -> str | None:
        """Send command and return raw response text (before 'ready...').

        Does NOT acquire the connection lock — callers must hold it already,
        or call this from within an already-locked context.
        """
        # Defence-in-depth: reject embedded newlines before they reach the device
        if "\n" in cmd or "\r" in cmd:
            log_debug(_LOGGER, "_async_send_raw", "Rejected command containing newline", cmd=cmd)
            return None
        if self._writer is None:
            log_debug(_LOGGER, "_async_send_raw", "Not connected, cannot send command")
            return None
        try:
            # Pass command through unchanged — callers are responsible for correct case.
            # Read commands use lowercase (@dat, @sta, @inf, @rel, @hwr).
            # Write commands use uppercase (@REL, @BOO, @PAR, @PRS, @CLK).
            to_send = cmd + "\n"
            self._writer.write(to_send)
            await self._writer.drain()
            response = await self._async_read_until("ready...", self._timeout)
            if not response or "ready..." not in response:
                return None
            return response.split("ready...")[0].strip()
        except (TimeoutError, OSError, AttributeError) as err:
            log_debug(_LOGGER, "_async_send_raw", "Command failed", cmd=cmd, error=err)
            return None

    async def async_send_boost(self, power: int, duration: int) -> bool:
        """Send @BOO command to control Power Reducer boost mode.

        power:    0-10000 (10000=100%).
        duration: seconds. 1=return to AUTO, 65535=permanent OFF, other=timed boost.
        Returns True if the command was accepted by the device.
        """
        if not (0 <= power <= 10000):
            raise ValueError(f"power {power} out of range [0, 10000]")
        if duration < 0:
            raise ValueError(f"duration {duration} must be non-negative")
        async with self._connection_lock:
            try:
                await self._ensure_connected()
                cmd = f"@BOO {power} {duration}"
                log_debug(
                    _LOGGER,
                    "async_send_boost",
                    "Sending boost command",
                    power=power,
                    duration=duration,
                )
                raw = await self._async_send_raw(cmd)
                if raw is None:
                    await self._safe_close()
                    return False
                self._last_activity = time.time()
                log_debug(
                    _LOGGER,
                    "async_send_boost",
                    "Boost command sent",
                    power=power,
                    duration=duration,
                )
            except (TelnetConnectionError, OSError, TimeoutError) as err:
                await self._safe_close()
                log_debug(_LOGGER, "async_send_boost", "Boost command failed", error=err)
                return False
            else:
                return True

    async def _async_read_clock(self) -> str | None:
        """Read device clock UTC string.

        Internal — must be called while holding the connection lock.
        Returns "DD.MM.YYYY HH:MM:SS" string, or None if unavailable.
        """
        raw = await self._async_send_raw("@clk")
        if raw is None:
            return None
        for line in raw.splitlines():
            if line.upper().startswith("UTC:"):
                return line.split(":", 1)[1].strip()
        return None

    async def _async_set_clock(self) -> bool:
        """Write current UTC time to the device clock.

        Internal — must be called while holding the connection lock.
        Returns True if the command was accepted.
        """
        now_utc = datetime.now(UTC).strftime("%d.%m.%Y %H:%M:%S")
        raw = await self._async_send_raw(f"@CLK {now_utc}")
        return raw is not None

    async def async_sync_clock(self) -> bool:
        """Public: acquire lock, sync device clock, return True on success."""
        async with self._connection_lock:
            try:
                await self._ensure_connected()
                ok = await self._async_set_clock()
                if ok:
                    self.data["clock_drift"] = 0
                self._last_activity = time.time()
            except (TelnetConnectionError, OSError, TimeoutError) as err:
                await self._safe_close()
                log_debug(_LOGGER, "async_sync_clock", "Clock sync failed", error=err)
                return False
            else:
                return ok

    async def async_read_par(self, param: str) -> int | None:
        """Read a PAR parameter value from the device.

        Returns the integer value, or None if the read fails.
        Raises ValueError for unknown or invalid parameter names.
        """
        if param.upper() not in self._ALLOWED_PAR_PARAMS:
            raise ValueError(f"Unknown PAR parameter: {param!r}")
        async with self._connection_lock:
            try:
                await self._ensure_connected()
                raw = await self._async_send_raw(f"@PAR {param}")
                if raw is None:
                    return None
                # Response: "@PAR\nPAR SPF_LDW 1850 W" — find the data line
                for line in raw.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 4 and parts[0].upper() == "PAR":
                        try:
                            result = int(parts[2])
                            self._last_activity = time.time()
                        except ValueError:
                            return None
                        else:
                            return result
            except (TelnetConnectionError, OSError, TimeoutError, ValueError) as err:
                await self._safe_close()
                log_debug(_LOGGER, "async_read_par", "Read PAR failed", param=param, error=err)
                return None
        return None  # No matching PAR line found

    async def async_write_par(self, param: str, value: int) -> bool:
        """Write a PAR parameter value to the device.

        Returns True if successful.
        Raises ValueError for unknown or invalid parameter names.
        """
        if param.upper() not in self._ALLOWED_PAR_PARAMS:
            raise ValueError(f"Unknown PAR parameter: {param!r}")
        async with self._connection_lock:
            try:
                await self._ensure_connected()
                raw = await self._async_send_raw(f"@PAR {param} {value}")
                if raw is None:
                    await self._safe_close()
                    return False
                # Non-None raw means the device responded with "ready..." — accepted.
                # Update local cache; the param key is lowercase (e.g. "spf_ldw").
                self.data[param.lower()] = value
                self._last_activity = time.time()
                log_debug(_LOGGER, "async_write_par", "PAR written", param=param, value=value)
            except (TelnetConnectionError, OSError, TimeoutError) as err:
                await self._safe_close()
                log_debug(_LOGGER, "async_write_par", "Write PAR failed", param=param, error=err)
                return False
            else:
                return True

    async def async_read_schedule(self, day: int) -> list[str] | None:
        """Read the Power Reducer schedule for a day.

        Device convention: 0=Sunday, 1=Monday, ..., 6=Saturday (US week order).
        Confirmed by telnet test: writing to day 0 → appears as Sunday in the app.

        Returns a list of 48 human-readable slot strings: 'off', 'auto', or 'boost'.
        Device read values: see _SCHEDULE_READ_MAP (0=OFF, 1=BOOST, 2=AUTO).
        """
        if not 0 <= day <= 6:
            raise ValueError(f"day {day} out of range [0, 6]")
        async with self._connection_lock:
            try:
                await self._ensure_connected()
                raw = await self._async_send_raw(f"@PRS 0 {day}")
                if raw is None:
                    return None
                # Response: "@PRS <day>;<slot0>;...;<slot47>;" — strip command echo prefix
                stripped = raw
                if stripped.upper().startswith("@PRS"):
                    stripped = stripped[4:].strip()
                parts = stripped.split(";")
                # parts[0] = day index echo, parts[1..48] = slot values, trailing empty
                values = [v.strip() for v in parts[1:] if v.strip()]
                if len(values) != 48:
                    log_debug(
                        _LOGGER,
                        "async_read_schedule",
                        "Unexpected slot count",
                        expected=48,
                        got=len(values),
                    )
                    return None
                self._last_activity = time.time()
                result: list[str] = []
                for v in values:
                    mode = self._SLOT_MODES.get(v)
                    if mode is None:
                        log_warning(
                            _LOGGER,
                            "async_read_schedule",
                            "Unknown slot value from device, defaulting to auto",
                            value=v,
                        )
                        mode = "auto"
                    result.append(mode)
            except (TelnetConnectionError, OSError, TimeoutError) as err:
                await self._safe_close()
                log_debug(
                    _LOGGER, "async_read_schedule", "Read schedule failed", day=day, error=err
                )
                return None
            else:
                return result

    async def async_write_schedule(self, day: int, slots: list[str]) -> bool:
        """Write the Power Reducer schedule for a day.

        Device convention: 0=Sunday, 1=Monday, ..., 6=Saturday (US week order).

        slots: list of exactly 48 strings, each 'off', 'auto', or 'boost'.
        Write mapping: see _SCHEDULE_WRITE_MAP (off=0, auto=2, boost=1).
        Each 8-slot group is reversed before sending (device stores groups right-to-left).
        """
        if not 0 <= day <= 6:
            raise ValueError(f"day {day} out of range [0, 6]")
        if len(slots) != 48:
            log_debug(_LOGGER, "async_write_schedule", "Invalid slot count", count=len(slots))
            return False
        invalid = [s for s in slots if s.lower() not in self._SLOT_WRITE]
        if invalid:
            log_debug(
                _LOGGER,
                "async_write_schedule",
                "Invalid slot values rejected",
                invalid=invalid[:5],
            )
            return False
        chars = [self._SLOT_WRITE[s.lower()] for s in slots]
        # Format as 6 groups of 8 characters, space-separated.
        # The device stores each group in reverse order (right-to-left), so each
        # group must be reversed before sending to get the correct slot mapping.
        # Confirmed by test: writing "11112222" reads back as "2222;1111".
        groups = ["".join(chars[i : i + 8][::-1]) for i in range(0, 48, 8)]
        data_str = " ".join(groups)
        async with self._connection_lock:
            try:
                await self._ensure_connected()
                raw = await self._async_send_raw(f"@PRS 1 {day} {data_str}")
                if raw is None:
                    await self._safe_close()
                    return False
                self._last_activity = time.time()
                log_debug(_LOGGER, "async_write_schedule", "Schedule written", day=day)
            except (TelnetConnectionError, OSError, TimeoutError) as err:
                await self._safe_close()
                log_debug(
                    _LOGGER, "async_write_schedule", "Write schedule failed", day=day, error=err
                )
                return False
            else:
                return True

    def reset_par_cache(self) -> None:
        """Reset PAR fetch cache to force re-read from device on next poll."""
        self._par_fetched = False
        log_debug(_LOGGER, "reset_par_cache", "PAR cache reset")

    async def async_get_data(self) -> bool:
        """Read Data Function.

        Uses connection pooling to prevent socket exhaustion on embedded device.
        Connection is reused if last activity was within CONNECTION_REUSE_TIMEOUT.

        All I/O operations are fully async - no event loop blocking.
        """
        # Use lock to prevent race conditions between polling and switch commands
        async with self._connection_lock:
            log_debug(
                _LOGGER,
                "async_get_data",
                "========== READ CYCLE START ==========",
            )
            try:
                # Use connection pooling - reuse existing connection if valid
                await self._ensure_connected()

                log_debug(_LOGGER, "async_get_data", "Fetching device data")
                dat_parsed = await self._require_data("@dat")

                log_debug(_LOGGER, "async_get_data", "Parsing @dat data")
                for key, value in dat_parsed.items():
                    # @dat returns only numbers as strings
                    # power/energy as float all others as int
                    try:
                        if ("energy" in key) or ("power" in key):
                            self.data[key] = round(float(value), 2)
                        elif key == "utc_time":
                            pass  # Redundant; clock is managed via _async_read_clock/@clk
                        else:
                            self.data[key] = int(value)
                    except ValueError:
                        log_debug(
                            _LOGGER,
                            "async_get_data",
                            "Value could not be parsed",
                            key=key,
                            value=value,
                        )
                        continue

                sta_parsed = await self._require_data("@sta")

                log_debug(_LOGGER, "async_get_data", "Parsing @sta data")
                for key, value in sta_parsed.items():
                    # @sta returns only float numbers as strings
                    try:
                        self.data[key] = round(float(value), 2)
                    except ValueError:
                        log_debug(
                            _LOGGER,
                            "async_get_data",
                            "Value could not be parsed",
                            key=key,
                            value=value,
                        )

                inf_parsed = await self._require_data("@inf")

                log_debug(_LOGGER, "async_get_data", "Parsing @inf data")
                for key, value in inf_parsed.items():
                    # @inf returns only strings
                    self.data[key] = str(value)

                # Calculated sensor to combine TOP/BOTTOM fw versions
                self.data["swver"] = f"{self.data['fwtop']} / {self.data['fwbtm']}"

                # Post-process boost fields and compute pr_mode.
                # Device reports boost_delay/boost_remaining as -1 when force_off
                # (@BOO 0 65535 — the unsigned 65535 wraps to -1 as a signed value).
                boost_active = int(self.data.get("boost_active", 0))
                boost_delay_raw = int(self.data.get("boost_delay", 0))

                if boost_active == 0:
                    # AUTO: no boost active — reset stale values (device omits them)
                    self.data["boost_remaining"] = 0
                    self.data["boost_power"] = 0.0
                    self.data["boost_delay"] = 0
                    self.data["pr_mode"] = "auto"
                elif boost_delay_raw == -1:
                    # FORCE OFF: permanent, device reports delay/remaining as -1
                    self.data["boost_remaining"] = 0
                    self.data["boost_power"] = 0.0
                    self.data["boost_delay"] = 0
                    self.data["pr_mode"] = "force_off"
                else:
                    # BOOST: timed — convert seconds to minutes and bp to % for display
                    self.data["boost_remaining"] = max(
                        0, int(self.data.get("boost_remaining", 0)) // 60
                    )
                    self.data["boost_delay"] = max(0, int(self.data.get("boost_delay", 0)) // 60)
                    self.data["boost_power"] = round(
                        float(self.data.get("boost_power", 0)) / 100.0, 2
                    )
                    self.data["pr_mode"] = "boost"

                # Convert Power Reducer output from device basis points
                # (0-10000, 10000=100%) to percentage (0.0-100.0) for display.
                self.data["reducer_power"] = round(
                    float(self.data.get("reducer_power", 0)) / 100.0, 2
                )

                # Fetch PAR parameters once per session (reset via reset_par_cache /
                # Refresh Parameters button, or automatically retried if fetch fails).
                if not self._par_fetched:
                    log_debug(_LOGGER, "async_get_data", "Fetching PAR parameters")
                    par_ok = True
                    for param, key in (("SPF_LDW", "spf_ldw"), ("SPF_SPW", "spf_spw")):
                        raw_par = await self._async_send_raw(f"@PAR {param}")
                        if raw_par:
                            # Response: "@PAR\nPAR SPF_LDW 1850 W" — find the data line
                            for line in raw_par.splitlines():
                                parts = line.strip().split()
                                if len(parts) >= 4 and parts[0].upper() == "PAR":
                                    with suppress(ValueError):
                                        self.data[key] = int(parts[2])
                                    break
                        else:
                            par_ok = False
                    # Only mark fetched if all reads succeeded — retry on next cycle if not
                    if par_ok:
                        self._par_fetched = True
                    else:
                        log_debug(_LOGGER, "async_get_data", "PAR fetch incomplete, will retry")

                # Clock management: read device clock, compute drift, auto-sync if needed
                utc_str = await self._async_read_clock()
                if utc_str:
                    try:
                        device_dt = datetime.strptime(utc_str, "%d.%m.%Y %H:%M:%S").replace(
                            tzinfo=UTC
                        )
                        self.data["device_clock_utc"] = device_dt
                        drift = int((device_dt - datetime.now(UTC)).total_seconds())
                        self.data["clock_drift"] = drift
                        if abs(drift) > CLOCK_DRIFT_THRESHOLD:
                            log_debug(
                                _LOGGER,
                                "async_get_data",
                                "Clock drift exceeds threshold, syncing",
                                drift=drift,
                            )
                            await self._async_set_clock()
                            self.data["clock_drift"] = 0
                    except ValueError:
                        log_debug(
                            _LOGGER,
                            "async_get_data",
                            "Could not parse device clock",
                            utc_str=utc_str,
                        )

                # Calculated sensors for self-consumption sensors
                self.data["self_consumed_power"] = round(
                    float(self.data["produced_power"]) - float(self.data["sold_power"]),
                    2,
                )

                self.data["self_consumed_energy"] = round(
                    float(self.data["produced_energy"]) - float(self.data["sold_energy"]),
                    2,
                )

                self.data["self_consumed_energy_f1"] = round(
                    float(self.data["produced_energy_f1"]) - float(self.data["sold_energy_f1"]),
                    2,
                )
                self.data["self_consumed_energy_f2"] = round(
                    float(self.data["produced_energy_f2"]) - float(self.data["sold_energy_f2"]),
                    2,
                )
                self.data["self_consumed_energy_f3"] = round(
                    float(self.data["produced_energy_f3"]) - float(self.data["sold_energy_f3"]),
                    2,
                )

                # Update last activity time for connection reuse
                self._last_activity = time.time()
                log_debug(
                    _LOGGER,
                    "async_get_data",
                    "========== READ CYCLE END (success) ==========",
                )

            except (TimeoutError, OSError) as err:
                # Connection error - close and force reconnect on next attempt
                await self._safe_close()
                log_debug(
                    _LOGGER,
                    "async_get_data",
                    "Connection or operation timed out",
                    error=err,
                )
                log_debug(
                    _LOGGER,
                    "async_get_data",
                    "========== READ CYCLE END (timeout) ==========",
                )
                raise TelnetConnectionError(
                    self._host, self._port, self._timeout, f"Connection error: {err}"
                ) from err
            except (TelnetConnectionError, TelnetCommandError):
                # Close on error to force fresh connection next time
                await self._safe_close()
                log_debug(
                    _LOGGER,
                    "async_get_data",
                    "========== READ CYCLE END (command error) ==========",
                )
                raise
            else:
                return True

    async def telnet_set_relay(self, state: str) -> bool:
        """Send Telnet Commands and process output.

        Uses connection pooling to prevent socket exhaustion on embedded device.
        Uses same lock as async_get_data() to prevent race conditions.

        All I/O operations are fully async - no event loop blocking.
        """
        set_relay = False

        to_state: int
        if state.lower() == "on":
            to_state = 1
        elif state.lower() == "off":
            to_state = 0
        else:
            return set_relay

        # Use lock to prevent race conditions between polling and switch commands
        async with self._connection_lock:
            try:
                # Use connection pooling - reuse existing connection if valid
                await self._ensure_connected()

                log_debug(
                    _LOGGER,
                    "telnet_set_relay",
                    "Sending relay command",
                    to_state=to_state,
                )

                # Send set relay command with retry (uppercase @REL per protocol spec)
                raw_set: str | None = None
                for attempt in range(COMMAND_RETRY_COUNT + 1):
                    raw_set = await self._async_send_raw(f"@REL 0 {to_state}")
                    if raw_set is not None:
                        break
                    if attempt < COMMAND_RETRY_COUNT:
                        log_debug(
                            _LOGGER,
                            "telnet_set_relay",
                            "Set relay command failed, retrying",
                            attempt=attempt + 1,
                            max_retries=COMMAND_RETRY_COUNT,
                        )
                        await asyncio.sleep(COMMAND_RETRY_DELAY)
                        await self._safe_close()
                        await self._ensure_connected()
                if raw_set is None:
                    log_debug(
                        _LOGGER,
                        "telnet_set_relay",
                        "Set relay command failed after retries",
                    )
                    await self._safe_close()
                    return set_relay

                # Read relay state with retry
                rel_parsed = await self._get_data_with_retry("@rel")

                # if we had a valid response we process data
                if rel_parsed:
                    rel_output = dict(rel_parsed.items())
                    log_debug(
                        _LOGGER,
                        "telnet_set_relay",
                        "Relay output",
                        rel_output=rel_output,
                    )
                    out_mode = int(rel_output["rel"])
                    log_debug(
                        _LOGGER,
                        "telnet_set_relay",
                        "Sent telnet command",
                        command=f"@REL 0 {to_state}",
                        rel=out_mode,
                    )
                    if out_mode == to_state:
                        set_relay = True
                        # refresh relay_state value to avoid waiting for poll cycle
                        self.data["relay_state"] = out_mode
                        log_debug(
                            _LOGGER,
                            "telnet_set_relay",
                            "Set relay success",
                            to_state=to_state,
                            rel=out_mode,
                            relay_state=self.data["relay_state"],
                        )
                    else:
                        set_relay = False
                        log_debug(
                            _LOGGER,
                            "telnet_set_relay",
                            "Set relay failure",
                            to_state=to_state,
                            rel=out_mode,
                            relay_state=self.data["relay_state"],
                        )
                else:
                    log_debug(_LOGGER, "telnet_set_relay", "rel_parsed is None")
                    # Force reconnect on next attempt
                    await self._safe_close()

                # Update last activity time for connection reuse
                self._last_activity = time.time()

            except TimeoutError:
                await self._safe_close()
                log_debug(_LOGGER, "telnet_set_relay", "Connection or operation timed out")
                set_relay = False
            except TelnetConnectionError:
                # Already closed by _ensure_connected failure
                log_debug(_LOGGER, "telnet_set_relay", "Connection failed")
                set_relay = False
            except OSError as ex:
                await self._safe_close()
                log_debug(_LOGGER, "telnet_set_relay", "Connection error", error=ex)
                set_relay = False

        log_debug(_LOGGER, "telnet_set_relay", "End telnet_set_relay", result=set_relay)
        return set_relay
