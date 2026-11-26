# Deye Modbus for Home Assistant

A fork of https://github.com/keeepcool/deye-modbus-ha (itself a fork of https://github.com/Developer089/deye-modbus-ha) that adds **optional, guarded write support** for the single-phase SG05LP1 hybrid inverters.

It retains the original project credits and licence. It is not affiliated with or endorsed by the original authors or Deye.

Out of the box it behaves exactly like upstream: **read only**. Writes only become possible after you enable *Allow changing inverter settings* in the integration options — see [Changing inverter settings](#changing-inverter-settings).

Local Home Assistant integration for:
 - **Deye single-phase hybrid inverters** - SG05LP1 family, tested on SUN-6K-SG05LP1-AM2-EU.
 - **Deye three-phase hybrid inverters** - SUN-\*K-SG04LP3 / SG05LP3 family, including the SUN-12K-SG05LP3.
 
Communication is performed locally over Modbus TCP, either through the inverter's WiFi/LAN logger or an RS485-to-TCP gateway. No cloud connection or SolarMAN account is required.

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Integration](https://img.shields.io/badge/type-local__polling-brightgreen.svg)](#)

> This is a **custom repository** for HACS. It is not (yet) in the default HACS store, so you add it manually — see [Installation](#installation).

---

## Features

- 100% **local polling** over Modbus TCP — nothing leaves your network.
- Talks directly to the Deye WiFi/LAN logger (default port **8899**) or to an RS485↔TCP gateway (Elfin EW11, USR, etc. — usually port **502**).
- Guided **config flow**: pick your inverter model from a dropdown, then enter host, port, Modbus unit ID and scan interval. No YAML editing needed.
- Rich set of **sensors**: PV strings, battery, grid import/export, per-phase grid/inverter/load, temperatures, plus daily and lifetime energy counters (ready for the HA Energy dashboard).
- Driven by a human-readable **YAML register map** — adding a model is just a new map file, no code changes.
- **Options flow** to tune scan interval, transport, address offset and serial parameters at any time.
- **Read-only by default**: optional, guarded control entities (battery limits, grid charge, work mode, time of use) for the single-phase SG05LP1.
- `pymodbus` is pulled in automatically by Home Assistant via the manifest.

---

## Installation

### Via HACS (recommended)

1. In Home Assistant go to **HACS**.
2. Open the top-right menu **⋮ → Custom repositories**.
3. Add the repository URL `https://github.com/witxo/deye-sg5-modbus-ha` and choose category **Integration**.
4. Find **Deye Modbus (Hybrid Inverter)** in the list and click **Download / Install**.
5. **Restart Home Assistant.**
6. Go to **Settings ▸ Devices & Services ▸ Add Integration** and search for **Deye Modbus**.

### Manual installation

1. Copy the folder `custom_components/deye_modbus` from this repository into your Home Assistant `/config/custom_components/` directory, so you end up with `/config/custom_components/deye_modbus/`.
2. **Restart Home Assistant.**
3. Add the integration via **Settings ▸ Devices & Services ▸ Add Integration → "Deye Modbus local interface"**.

---

## Configuration

When you add the integration you get a single setup form:

| Field | Default | Notes |
|-------|---------|-------|
| **Inverter model** | SUN-6K-SG05LP1 | Dropdown; selects the bundled register map. |
| **Host / IP** | — | IP address of the inverter's logger or your RS485↔TCP gateway, e.g. `192.168.x.x`. |
| **Port** | `8899` | See the port guidance below. |
| **Modbus unit ID** | `1` | The Modbus slave/device address. Leave at `1` unless you changed it on a gateway. |
| **Scan interval (s)** | `15` | How often to poll, range **5–300** seconds. |

### Which port should I use?

- **`8899`** — the Deye/SolarMAN **WiFi or LAN stick logger** exposes Modbus TCP on this port. This is the right choice for most people plugging into the inverter's own logger.
- **`502`** — a third-party **RS485-to-TCP gateway** (Elfin EW11, USR, etc.) wired to the inverter's Modbus/BMS RS485 port. These typically speak standard Modbus TCP on 502.

If you are unsure, try `8899` first; if no data appears, try `502`.

### Finding the inverter's IP

Look in your router's DHCP client list for the logger (often named `Solarman*` / `IGEN*` / the stick's serial), or use the SolarMAN app / a network scanner. Assigning it a static DHCP lease is recommended so the address never changes.

---

## Supported models

### Single-phase hybrid

Should be compatible with all other SG05LP1 single-phase models as well.

| Model key | Label |
|---|---|
| SG05LP1 | SUN-6K-SG05LP1-EU-AM2 |

### Three-phase hybrid

All of these share the three-phase low-voltage hybrid protocol (device type `0x0500`) and the same register map:

| Model key | Label |
|-----------|-------|
| `sun12k_sg05lp3` | Deye SUN-12K-SG05LP3 (3-phase hybrid) |
| `sun_sg05lp3_3ph` | Deye SUN-5/6/8/10/12K-SG05LP3 (3-phase hybrid) |
| `sun_sg04lp3_3ph` | Deye SUN-5/6/8/10/12K-SG04LP3 (3-phase hybrid) |

Rebadged units on the same platform (Sunsynk, etc.) will generally work too.

---

## Entities overview

### Sensors (selection)

| Area | Entities |
|------|----------|
| Status | Run State |
| PV | PV1/PV2 voltage, current, power (PV3/PV4 available on three-phase models only, disabled by default) |
| Battery | SOC, voltage, current, power, temperature (corrected capacity disabled by default) |
| Grid / CT | Grid voltage L-N or L1–L3, frequency, per-phase power, total grid power (import +, export −) |
| Inverter | Inverter total power |
| Load | Total load power |
| Backup / Generator | Backup power, generator voltage/power (disabled by default) |
| Temperatures | AC (radiator) temperature, DC temperature |
| Energy — today | PV production, battery charge/discharge, grid import/export, load consumption |
| Energy — total | PV production, battery charge/discharge, grid import/export, load consumption (32-bit lifetime counters) |

---

## Options

Open the integration and click **Configure** to change (no restart needed — the entry reloads):

- **Scan interval** — 5–300 s.
- **Transport** — `tcp` (standard Modbus TCP) or `rtutcp` (RTU frame over a raw TCP socket, for some gateways).
- **Address offset** — added to every register address, for gateways that shift the map.
- **Serial parameters** — baud rate, byte size, parity (N/E/O), stop bits (only relevant for `rtutcp`).
- **Allow changing inverter settings** — off by default. See below.

---

## Changing inverter settings

Only the single-phase map (`sun_1ph_hybrid.yaml`, `writes_supported: true`) has verified writable registers. The three-phase map keeps its control definitions but they are not loaded.

When enabled, these entities appear (entity category *Configuration*):

| Entity | Type | Register | Range |
|---|---|---|---|
| Battery Max Charge / Discharge Current | number | 210 / 211 | 0–135 A |
| Battery Shutdown / Restart / Low SOC | number | 217 / 218 / 219 | must keep shutdown < low < restart |
| Grid Charge | switch | 232 | on / off |
| Grid Charge Current | number | 230 | 0–135 A |
| Energy Pattern | select | 243 | Battery First / Load First |
| Work Mode | select | 244 | Selling First / Zero Export To Load / Zero Export To CT |
| Max Sell Power | number | 245 | 0–6000 W |
| Solar Sell | switch | 247 | on / off |
| Time Of Use | switch | 248 bit 0 | weekday bits untouched |
| TOU 1–6 Start | time | 250–255 | HHMM, must stay in ascending order |
| TOU 1–6 Power | number | 256–261 | 0–6000 W |
| TOU 1–6 SOC | number | 268–273 | 5–100 % |
| TOU 1–6 Grid Charge | switch | 274–279 bit 0 | other bits untouched |

Deliberately **not** exposed: GEN port mode and settings (235–239, e.g. an AC-coupled inverter on the GEN input), battery type and voltages, grid/country parameters and inverter on/off.

Safety checks, all enforced in the coordinator so no entity or automation can skip them:

1. writes must be enabled in the options, and the map must declare `writes_supported`;
2. the register must be a control in the map and the value inside its range;
3. at most one write per register every 30 s (protects the inverter's settings flash — do not drive these from fast automations);
4. a write is skipped when the register already holds the value;
5. bit fields are read-modify-write; other bits are preserved;
6. after writing, the register is read back; a mismatch raises an error and the entity shows the real value;
7. every change is logged as a warning: `Deye register 211 changed 135 -> 100`.

Writes use FC16 (write multiple registers) even for a single register, because Deye inverters reject FC06. Settings registers are re-read every 4th poll (and right after a write) to keep the Modbus load low.

### Tests

```bash
pip install -r requirements_test.txt
pytest
```

The tests run a real Modbus TCP server holding a register image captured from a SUN-6K-SG05LP1, and exercise the safety checks and every entity type end to end.

- Perfomance can be tuned 

---


## How it works / Modbus notes

- **Everything is read with function code `0x03` (FC03, read holding registers)** — on this inverter both the live measurements and the writable settings live in the holding-register space.
- **32-bit energy counters are stored low-word-first** (`word_order: low_high`, little-endian by word). The integration reassembles them automatically.
- **Grid Import Total** register spans two non contiguous registers, **second_address** was added to allow the correct reading of this data. 
- **Temperatures** use a raw offset of 1000 and scale 0.1, i.e. `°C = (raw − 1000) × 0.1`.A raw value of zero therefore decodes to -100 °C. This indicates an unavailable or unused temperature sensor, not an actual measurement.
- **Signed values** (battery/grid/load power and current) are decoded as two's-complement. Grid total power is **positive when importing, negative when exporting**.
- The register map is a plain YAML file (`custom_components/deye_modbus/maps/sun_3ph_hybrid.yaml` and ) derived from Deye's official three-phase energy-storage Modbus protocol document, single-phase register was built using information from https://github.com/tema-mazy/deye-modbus-test and https://github.com/VMrenato/homeassistant-deye-tcan485-esphome.

### Modbus read grouping and gateway compatibility

The integration groups nearby register reads to reduce the number of Modbus requests sent to the inverter.

Two parameters in `coordinator.py`, inside `_read_grouped()`, control this behaviour:

- `MAX_WORDS`: Maximum number of consecutive registers requested in a single Modbus read.
- `GAP`: Maximum number of unused registers allowed between requested register ranges before they are grouped into the same read.

**Adjusting these values**

Different Deye loggers and RS485-to-TCP gateways can behave differently when handling larger Modbus requests. If you experience intermittent read errors, missing sensor values or communication timeouts, reducing `MAX_WORDS` is a good first troubleshooting step.

For example:

```python
GAP = 0
MAX_WORDS = 5
```

This configuration reads only consecutive registers and limits each grouped request to five registers. It can improve compatibility with gateways that struggle with larger Modbus reads.

If your gateway handles larger requests reliably, you can experiment with increasing `MAX_WORDS` to reduce the number of requests. Increasing `GAP` may also reduce request count, but causes additional unused registers to be read.

**Important:** These are internal integration parameters, not Home Assistant configuration options. Changes require restarting Home Assistant to take effect. The optimal values depend on the inverter, logger and gateway combination.

---

## Troubleshooting

- **No data / entities unavailable.** Double-check the **port** (`8899` for the Deye logger vs `502` for an RS485↔TCP gateway) and the **Modbus unit ID** (usually `1`). Confirm the IP is reachable from the HA host (`ping`), and that the logger firmware is recent.
- **Only one Modbus master at a time.** The inverter/logger accepts a **single** Modbus connection. This integration will **conflict with the SolarMAN cloud logging and with any other Modbus poller** (a second HA integration, Node-RED, etc.). If the SolarMAN app / cloud is actively connected you may see dropouts — expect to give up cloud logging, or poll via a separate RS485 gateway.
- **Intermittent timeouts.** Increase the **scan interval**, reduce competing connections, or improve WiFi signal to the logger. For flaky gateways try the `rtutcp` transport in Options.
- **Wrong or shifted values.** If a gateway shifts the address map, set an **address offset** in Options.

---

## Disclaimer

This is an unofficial community-maintained fork.

Changing inverter settings is at your own risk. Write a note of your current settings before you enable writes, and change one setting at a time while watching the inverter's display or app.

Always verify the register map and measurements against your inverter before relying on them for automation or other purposes.

---

## Credits

- Original project architecture and implementation: Developer089/deye-modbus-ha; single-phase support and read-only hardening: keeepcool/deye-modbus-ha.
- Architecture modeled on a **Growatt Modbus** Home Assistant integration (coordinator + YAML-driven register map pattern).
- Register map for the three phase models derived from **Deye's official Modbus protocol documentation** for the three-phase energy-storage (hybrid) inverters.
- Register map for the models derived and validated from https://github.com/tema-mazy/deye-modbus-test and https://github.com/VMrenato/homeassistant-deye-tcan485-esphome.
- Built on [`pymodbus`](https://github.com/pymodbus-dev/pymodbus).

---