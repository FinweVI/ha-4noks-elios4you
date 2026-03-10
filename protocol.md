# Elios4you Protocol Reference

## Transport

- **Protocol**: Plain TCP
- **Port**: 5001
- **Encoding**: ASCII (commands), binary (firmware upload)
- **Command terminator (send)**: `\r` (CR only)
- **Response delimiter**: `\r\n` (CRLF) — responses split on `\r\n`

---

## Encryption

### LAN (direct connection)
- Plaintext, no transformation

### Relay (remote via 4-noks relay server)
- Shift cipher
- Key: `shift = (sum_of_PIN_bytes & 0xFF) % 127`
- Encrypt: `(byte + shift) % 127 % 255`
- Decrypt: `byte > shift ? (byte - shift) % 127 : (byte + 127 - shift) % 127`
- Note: if PIN = "1" (or any PIN whose byte sum mod 127 = 1), this degenerates to ROT+1

### AES128
- AES128 encryption is defined in the protocol but not used in any observed communication.

---

## Handshake

### LAN Handshake
```
Client → @hwr\r
Server → HWVER=<12-char hex>\r\n
         ready...\r\n
```
If response does not contain `"HWVER"`, connection is rejected.

### Relay Handshake (via relay server)
```
Client → RelayList
Server → RelayListResp[ip:port,ip:port,...]

Client → DevDiscover[<serial>:<pin>:<appId>]
Server → DevDiscoverResp[OK]
```
Fallback attempt without `appId` if first attempt fails.

---

## Response Framing

- Most responses end with `ready...\r\n`
- Responses are accumulated until `"ready..."` is received, then split on `\r\n`
- Firmware upload exception: also terminates on `"@UPG START"`

---

## Command Reference

All commands use prefix `@` and are terminated with `\r`.

### Identity & Status

| Command | Description | Response format |
|---------|-------------|-----------------|
| `@hwr` | Hardware info | `HWVER=<12-char hex>` |
| `@inf` | Device info | See below |
| `@wfi` | WiFi info | `RSSI=<val>`, `CH=<val>` |
| `@srv` | Server connection status | `INIT=`, `LASTLOG=`, `CPERR=`, `DNSERR=`, `CONNERR=` |
| `@me0` | Ping / canTalk | Any response = alive |
| `@sca` | WiFi scan (10s timeout) | List of SSIDs |
| `@wel 1` | WiFi error log | `WEL=v1;v2;...;v12` |

#### `@inf` Response
```
FWTOP=<version>        (e.g., V1293build164)
FWBTM=<version>
SN=<serial>
HW WIFI=<module>
S2W APP VERSION=<ver>
S2W GEPS VERSION=<ver>
S2W WLAN VERSION=<ver>
```

#### `@hwr` Response — HWVER byte decoding
```
HWVER=<12-char hex string>
  [0:2]  = MC type: "00" → 128K, "01" → 256K (RedCap)
  [6:8]  = bit 0 → RS485 interface present
  [8:10] = vendor ID: "0C" → Reverberi EDI battery/diverter attached
  [11]   = '1' → PowerReducer compatible
```

---

### Live Data

| Command | Description |
|---------|-------------|
| `@dat` | Live measurement snapshot |
| `@sta` | Peak power statistics |

#### `@sta` Response
```
@STA
;Daily Peak;0.00;kW;
;Monthly Peak;7.81;kW;
```
Format: semicolon-delimited `;Label;Value;Unit;` — same parser as `@dat`.
Returns daily and monthly peak power values in kW.

#### `@dat` Key Fields
```
producedPower, consumedPower, withdrawnPower, intakenPower
relay_state, relay_mode
externalAlarm1, externalAlarm2
alarmNoProduction, withdrawnAlarm
mbs_enabled, mbs_comm_error
power_reducer_active, power_reducer_mode
demo_mode
taz_1_type, taz_1_online, taz_1_rssi
acc_battery_level, mbsvar_battery_temperature
mbsvar_battery_state, mbsvar_battery_alarm
acc_power  (kW, + = charging, - = discharging)
DEVHA
```

---

### Historical Data

| Command | Description |
|---------|-------------|
| `@met <epoch_sec> <count>` | Records starting at timestamp |
| `@me1` | Oldest record |
| `@me2` | Newest record |

#### Historical Record Format (semicolon-delimited, 17–20 fields)
```
<ts_epoch_sec>;<prodE>;<prodP>;<wdwnF1>;<wdwnF2>;<wdwnF3>;<wdwnE>;<wdwnP>;
<soldE>;<intP>;<consF1>;<consF2>;<consF3>;<consE>;<consP>;<alm1>;<alm2>
[;<mtrE+>;<mtrE->;<mtrP>]   ← optional, present if field count >= 20
```
Filter lines starting with: `@MET`, `@ME1`, `@ME2`, `ready...`, `UTC`

---

### Clock

| Command | Description |
|---------|-------------|
| `@CLK` | Read device clock |
| `@CLK <datetime>` | Set device clock |

- Format: `dd.MM.yyyy HH:mm:ss` (Locale.US, UTC)
- Response lines: `UTC: DD.MM.YYYY HH:MM:SS` and `LOCAL: DD.MM.YYYY HH:MM:SS`
- Sync threshold: 300 000 ms (5 minutes) — only syncs if drift > 5 min

---

### WiFi Configuration

```
@cfg ssid <ssid>
@cfg sec <type>
@cfg key <password>
@cfg dhcp 1|0
@cfg ip <ip>
@cfg mask <mask>
@cfg gw <gateway>
@cfg dns <dns>
@cfg apply 1        ← commits and reboots
```

---

### Relay Control

| Command | Description |
|---------|-------------|
| `@rel` | Read relay state |
| `@REL 0 0` | Manual OFF |
| `@REL 0 1` | Manual ON |
| `@REL 1 <low> <high> <dLow> <dHigh> [spf]` | Auto mode |
| `@REL 2` | Timer mode |

#### `@rel` Response Fields
```
MODE=<0=auto|1=manual|2=timer>
REL=<0=off|1=on>
LOW=<dW>         (divide by 10 for watts)
HIGH=<dW>
HIGH T=<seconds>
LOW T=<seconds>
SPF=<0|1>
```

---

### Relay Schedule

| Command | Description |
|---------|-------------|
| `@RLS 0 <day>` | Read relay schedule for day (0=Mon … 6=Sun) |
| `@RLS 1 <day> <tokens>` | Write relay schedule |

Schedule format: 48 slots × 30 min, semicolon-separated.

---

### Export Control (XPC)

| Command | Description |
|---------|-------------|
| `@XPC` | Read export control config |
| `@xpc <pwd> <params>` | Write export control config |
| `@xpc -` | Clear XPC password |

#### `@XPC` Response (line index 1)
```
<pwd>;<actThreshold>;<deactThreshold>;<actDelay>;<checkPeriod>
```
Constants: `ACTIVATION_CHECK_PERIOD_MAX = 3600`

---

### PowerReducer

| Command | Description |
|---------|-------------|
| `@PAR <name>` | Read parameter |
| `@PAR <name> <value>` | Write parameter |
| `@PAR ALL` | Read all parameters (one `PAR <NAME> <VALUE>` per line) |
| `@BOO 1 <seconds>` | Activate boost (always 10 000 W) |
| `@BOO 0 0` | (implied deactivation) |
| `@PRS 0 <day>` | Read PowerReducer schedule |
| `@PRS 1 <day> <tokens>` | Write PowerReducer schedule |

#### `@PAR ALL` Response Format
```
PAR <NAME> <VALUE>
PAR ALR1 "<quoted string>"
PAR ALR2 "<quoted string>"
```

#### All Known PAR Parameters

| Name | Default | Description |
|------|---------|-------------|
| `LANG` | 0 | Language |
| `HOL` | 0 | Holiday mode |
| `ZONE` | Europe/Rome | Timezone |
| `NOM` | 3 | Nominal power |
| `SPWR` | 3 | Setpoint power |
| `BIL` | 0 | Billing mode |
| `PRI` | 0 | Priority |
| `PRA` | 0 | Priority A |
| `VTT` | 0 | Voltage threshold |
| `PF1` | 0 | Power factor 1 |
| `PF23` | 0 | Power factor 2/3 |
| `TS1`–`TS4` | 0 | Time slots 1–4 |
| `ALR1` | "Alarm1" | Alarm 1 label |
| `ALR2` | "Alarm2" | Alarm 2 label |
| `BAL` | conn-srv.4-noks.com | Relay/report server hostname |
| `BPORT` | 1433 | Relay/report server port |
| `CUR` | — | Current (no default) |
| `TZO` | — | Timezone offset (no default) |
| `PWM_MOD` | — | PWM/PowerReducer mode (see below) |

#### PWM_MOD Values

| Value | Meaning |
|-------|---------|
| 0 | Disabled |
| 3 | PWM mode (simple modulation) |
| 4 | Full PowerReducer (PID controller, unlocks SPF_* params) |

#### PowerReducer PID Parameters (active when PWM_MOD=4)

| Name | Default | Unit | Description |
|------|---------|------|-------------|
| `SPF_LDW` | 1700 | W | Max controllable load power |
| `SPF_SPW` | 0 | W | Setpoint: net export above which PR activates |
| `SPF_PIT` | 10 | s | PID integration time Ti (higher = slower integral) |
| `SPF_PKP` | 10000 | — | Proportional gain Kp |
| `SPF_PKI` | 0 | — | Integral gain Ki |
| `SPF_PKD` | 0 | — | Derivative gain Kd |
| `SPF_PRI` | 0 | bool | Priority management enable |

**Hidden advanced settings**: entering code `8596` in the UI code field reveals the advanced SPF_* parameters (PKP, PKI, PKD).

#### Boost Durations (seconds)
`900, 1800, 2700, 3600, 5400, 7200, 9000, 10800, 14400, 65535 (forever)`

---

### Energy Counters

| Command | Description |
|---------|-------------|
| `@CNT <type> <slot>` | Read counter |
| `@CNT <type> <slot> <value>` | Write counter |
| `@CNT all` | All counters |

- Types: `PROD`, `SOLD`, `BOUG`
- Slots: `F1`, `F2`, `F3`

---

### Data Erase

| Command | Description |
|---------|-------------|
| `@ERS 1` | Clear all data → `ERS OK` |
| `@ERS 2` | Clear database → `ERS OK` |

---

### Modbus / MBS (RS485 output to Reverberi EDI battery)

> **Note**: This is NOT a Modbus server. It is an RS485 *output* interface to control
> Reverberi EDI battery/diverter units. Not usable as an HA data source.

| Command | Description |
|---------|-------------|
| `@MBS ENA` | Get Modbus enable state |
| `@MBS ENA 0\|1` | Set Modbus enable |
| `@MBS SPR` | Get serial parameter ID |
| `@MBS SPR <id>` | Set serial parameter ID |
| `@MBS ADR` | Get Modbus address |
| `@MBS ADR <addr>` | Set Modbus address |
| `@MBS COM <value>` | Send command to Reverberi EDI device |

#### Reverberi EDI Commands (`@MBS COM <value>`)
| Value | Hex | Action |
|-------|-----|--------|
| 32769 | 0x8001 | ALARM_RESET |
| 16386 | 0x4002 | SWITCH_ON |
| 8196 | 0x2004 | SWITCH_OFF |
| 4104 | 0x1008 | FORCE_RECHARGE |
| 2064 | 0x0810 | CANCEL_RECHARGE |

#### MBS Serial Parameter IDs (24 combinations)
```
{1,2,3,4, 9,10,11,12, 17,18,19,20, 25,26,27,28, 33,34,35,36, 41,42,43,44}
```
Likely: 6 baud rates × 4 parity/stop combinations.

---

### Firmware Update

```
Client → @upg <moduleId> <byteCount>\r
Server → @UPG START\r\n
Client → <raw binary data>
Server → @UPG OK\r\n
```

- Module IDs: `0` = TOP, `1` = BOTTOM
- Firmware file mapping: `<hwMark>,<fileTop>,<verTop>,<fileBottom>,<verBottom>`

---

## Polling Recommendations for Home Assistant

| Data | Command | Suggested interval |
|------|---------|-------------------|
| Live power/state | `@dat` | 10–15 s |
| Peak statistics | `@sta` | 10–15 s (same cycle as `@dat`) |
| Historical records | `@met` | 15 min |
| Clock sync check | `@CLK` | Once at startup |
| Relay state | `@rel` | On demand / 30 s |

**Do not use `BAL`/`BPORT` redirection** — these point to the 4-noks relay server which also
handles remote app access via a proprietary protocol. Changing them breaks remote connectivity
and offers no benefit if reading via LAN telnet.
