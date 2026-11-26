# Deye SG05 Modbus (Hybrid Inverter)

Local Home Assistant integration for **Deye single-phase hybrid inverters** (SG05LP1 family, tested on SUN-6K-SG05 LP1 AM2 EU) and **Deye three-phase hybrid inverters** (SUN-\*K-SG04LP3 / SG05LP3 family, including the SUN-12K-SG05LP3).
 It polls the inverter over **Modbus TCP** directly, either through the Deye WiFi/LAN logger (default port **8899**) or an RS485-to-TCP gateway (port **502**). 
 No cloud, no SolarMAN account.

## What you get

- 100% local polling — nothing leaves your network.
- Sensors: PV strings, battery (SOC/power/temperature), grid import/export, per-phase grid/inverter/load, temperatures, plus daily and lifetime energy counters for the Energy dashboard.
- Guided config flow (pick model → host/port/unit ID/scan interval) and an options flow for transport, address offset and serial params.
- **Read-only by default** - optional, guarded writes (battery limits, grid charge, work mode, time of use) for the single-phase SG05LP1, enabled in the integration options.

Some entities (PV3/PV4, per-phase detail, TOU slots) ship **disabled by default** — enable them in the entity settings.

## Supported models

- Deye SUN-6K-SG05LP1 (1-phase hybrid)
- Deye SUN-3.6/5/7/7.6/8/10K-SG05LP1 (1-phase hybrid) - Not tested
- Deye SUN-12K-SG05LP3 (3-phase hybrid)
- Deye SUN-5/6/8/10/12K-SG05LP3 (3-phase hybrid)
- Deye SUN-5/6/8/10/12K-SG04LP3 (3-phase hybrid)

## Quick start

1. Install via HACS, then **restart Home Assistant**.
2. **Settings ▸ Devices & Services ▸ Add Integration → "Deye SG05 Modbus"**.
3. Pick your model and enter the logger IP (e.g. `192.168.x.x`), port (`8899` for the Deye logger, `502` for an RS485↔TCP gateway), Modbus unit ID (`1`) and scan interval.

> Note: the inverter accepts only **one Modbus connection at a time**, so this conflicts with SolarMAN cloud logging and other Modbus pollers.

See the [README](https://github.com/keeepcool/deye-modbus-ha) for the full entity list, options, services and troubleshooting.
