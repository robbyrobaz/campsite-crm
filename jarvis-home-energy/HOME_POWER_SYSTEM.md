# Home Power & Energy System — Master Documentation

> **Location:** Queen Creek, AZ
> **Utility:** SRP (Salt River Project) — demand-based plan
> **Dashboard:** http://192.168.68.72:8793
> **Last updated:** 2026-02-25

---

## System Overview

```
            SRP Grid (utility meter)
                    ↕
            Tesla Gateway 3              ← grid management, whole-home backup
                    ↕
         ┌─── SPAN Smart Panel ───┐
         │    Model 00200          │
         │    28 tabs / 21 circuits│
         │                         │
         ├── House Loads           │
         ├── AC Condensers (×2)    │
         ├── EV Charger (240V)     │
         ├── Oven / Dryer (240V)   │
         ├── Pool Sub-Panel ───────┼──→ Pentair IntelliCenter
         └─────────────────────────┘
                    ↑
         Solar feeds upstream into gateway/panel:
           • Enphase (~6 kW, 20 microinverters)
           • SolarEdge (~5.8 kWp, SE5000H-US)
```

**Combined solar capacity: ~11.8 kW**
**No battery storage.** The Tesla Gateway 3 manages grid interconnect and backup switching only — there is no Powerwall or any other battery in this system.

### Power Flow

1. **Solar** — two independent arrays produce AC (Enphase microinverters) and DC→AC (SolarEdge string inverter)
2. **Tesla Gateway 3** — sits between grid and panel; manages grid interconnect and whole-home backup switching
3. **SPAN Smart Panel** — distributes to all circuits with per-circuit monitoring and relay control
4. **SRP Grid** — imports when solar can't cover load, receives excess solar export

---

## Utility: SRP

| Detail | Value |
|--------|-------|
| **Provider** | Salt River Project |
| **Plan type** | Demand-based (time-of-use) |
| **Summer peak risk** | 7–9 PM |
| **Blended all-in rate** | ~$0.18/kWh |
| **Summer effective rate** | ~$0.23/kWh (demand charges included) |
| **Net metering** | Solar excess exported for credit |
| **Account integration** | Not yet configured (future: SRP API polling) |

---

## ☀️ Solar Systems (Dual Independent Arrays)

### 1. Enphase System (~6 kW)

| Detail | Value |
|--------|-------|
| **System size** | ~6.0 kW peak (20 × ~298W) |
| **Microinverters** | 20 active |
| **Microinverter part** | 800-01374-r02 |
| **Microinverter firmware** | 521-00005-r06-v02.61.01 |
| **Microinverter peak range** | 297–299W each |
| **Gateway** | Enphase IQ Gateway (Envoy) |
| **Gateway serial** | 202324023651 |
| **Gateway part** | 800-00663-r05 |
| **Gateway firmware** | D8.3.5167 (app 08.03.5167) |
| **Gateway MAC (WiFi)** | 90:48:46:90:6F:E1 |
| **Gateway MAC (Ethernet)** | 00:1D:C0:BE:35:F2 |
| **LAN IP** | 192.168.68.63 (`envoy.local`) |
| **Connectivity** | WiFi (primary) + Ethernet (not connected) |
| **Timezone** | US/Arizona |
| **Lifetime production** | ~29 MWh |
| **Weekly production** | ~265 kWh (typical) |
| **API** | Local HTTPS + Enphase Enlighten cloud |
| **Auth** | JWT (expires ~March 2027) |
| **Meters** | Production + consumption CTs on mains (imeter: true) |

**Software packages on gateway:**

| Package | Part | Version |
|---------|------|---------|
| agf | 500-00012-r01 | 02.02.00 |
| app | 500-00002-r01 | 08.03.5167 |
| backbone | 500-00010-r01 | 07.00.20 |
| boot | 590-00019-r01 | 02.00.01 |
| devimg | 500-00004-r01 | 01.02.550 |
| essimg | 500-00020-r01 | 31.43.13 |

**Microinverter serial numbers:**

| # | Serial | Max W | Phase |
|---|--------|-------|-------|
| 1 | 482302014187 | 298 | A |
| 2 | 482302014674 | 298 | A |
| 3 | 482302014787 | 297 | A |
| 4 | 482302014798 | 298 | A |
| 5 | 482302014831 | 298 | A |
| 6 | 482302014980 | 298 | A |
| 7 | 482302015009 | 298 | A |
| 8 | 482302015015 | 298 | A |
| 9 | 482302015191 | 299 | A |
| 10 | 482302015218 | 298 | A |
| 11 | 482302015227 | 298 | A |
| 12 | 482302015255 | 298 | A |
| 13 | 482302015276 | 298 | A |
| 14 | 482302015430 | 298 | A |
| 15 | 482302015459 | 299 | A |
| 16 | 482302016370 | 298 | A |
| 17 | 482302016388 | 298 | A |
| 18 | 482302016413 | 298 | A |
| 19 | 482302016414 | 298 | A |
| 20 | 482302016864 | 298 | A |

**How it works:** Each panel has its own microinverter (no single point of failure). The IQ Gateway aggregates production data, manages grid compliance, and provides a local JSON API. Production CTs measure panel output; consumption CTs on the mains measure total house load.

### 2. SolarEdge System (~5.8 kWp)

| Detail | Value |
|--------|-------|
| **Inverter** | SE5000H-US (string inverter) |
| **System size** | ~5.8 kWp |
| **Connectivity** | LTE only |
| **Local API** | Not enabled / no admin access currently |
| **Cloud API** | Data available via SolarEdge monitoring portal |

**Note:** This is a second, independent array with a single string inverter (vs Enphase's per-panel microinverters). No local API access at present — data only via SolarEdge cloud.

---

## ⚡ Tesla Gateway 3

| Detail | Value |
|--------|-------|
| **Model** | Tesla Energy Gateway 3 |
| **Function** | Grid management, whole-home backup switching |
| **Serial** | GF2240460002D2 |
| **Firmware** | 25.26.0 |
| **LAN IP** | 192.168.68.86 |
| **Energy Site ID** | 2252397277512276 ("My Home") |
| **API** | Tesla Fleet API (OAuth via `teslapy`) |
| **Local API status** | `/api/meters/aggregates` → 403, most others → 404 |

**How it works:** Sits between the SRP grid and the SPAN panel. Manages grid interconnection and provides whole-home backup switching capability. There is **no battery storage** (no Powerwall) — the Gateway manages solar-to-grid flows and can island the house during outages using solar only. All control and monitoring through the Tesla Fleet API; local endpoints are locked down.

**⚠️ No Powerwall. No battery. Solar + grid only.**

---

## 🚗 EV Infrastructure

### Tesla Cybertruck

| Detail | Value |
|--------|-------|
| **Powershare capable** | Yes |
| **Primary use** | Turo rental (>50% of time) |
| **Target renter return SoC** | ~50% |
| **Home charging cost** | ~$0.18/kWh |
| **Supercharger cost** | ~$0.42/kWh |
| **Optimal charge band** | 0–50% (fastest) |

### Tesla Universal Wall Connector

| Detail | Value |
|--------|-------|
| **Model** | Tesla Universal Wall Connector |
| **Part number** | 1734412-02-D |
| **Serial** | B7S24058J22706 |
| **Firmware** | 25.42.1+gd54dd6fc87801d |
| **Max current** | 48A |
| **LAN IP** | 192.168.68.87 |
| **WiFi SSID** | wirelessrob |
| **WiFi signal** | -37 dBm / SNR 57 (excellent) |
| **MAC** | 54:F8:F0:0E:B4:96 |
| **Panel circuit** | "Other EV charger" (tabs 26, 28 — 240V) |
| **Grid voltage** | ~243V |
| **API** | Local HTTP, no auth required |
| **Endpoints** | `/api/1/vitals`, `/api/1/lifetime`, `/api/1/version`, `/api/1/wifi_status` |
| **Cloud service** | h3-hermes-prd.sn.tesla.services |

**Lifetime stats:**

| Stat | Value |
|------|-------|
| Energy delivered | 9,585 kWh (9.6 MWh) |
| Charge starts | 849 |
| Contactor cycles | 849 (532 loaded) |
| Connector cycles | 390 |
| Charging time | 4,048,193 sec (~1,125 hours) |
| Total uptime | 36,219,384 sec (~419 days) |
| Thermal foldbacks | 39 |
| Alert count | 1,739 |

**How it works:** Hardwired 240V EVSE on a dedicated circuit. Communicates with Tesla vehicles via pilot wire. Reports real-time charging state, voltage, current, temps (PCBA, handle, MCU), and session energy via local API.

**Second EV circuit:** "CyberTruck 220v not used" (tabs 20, 22) is wired at the panel but not active — available for a second charger if needed.

---

## ⚡ Distribution: SPAN Smart Panel

| Detail | Value |
|--------|-------|
| **Manufacturer** | Span |
| **Model** | 00200 |
| **Serial** | nj-2307-006gl |
| **Firmware** | spanos2/r202603/05 |
| **Environment** | prod |
| **LAN IP** | 192.168.68.93 |
| **Connectivity** | WiFi (connected) + cellular/WWAN (connected) + Ethernet (not connected) |
| **Door state** | CLOSED |
| **API** | Local HTTP, Bearer token auth |
| **Tab positions** | 28 (serving 21 circuits) |
| **Monitoring branches** | 32 (21 circuits + 4 main bus feeds) |
| **Main relay** | CLOSED |
| **Grid state** | DSM_GRID_UP / DSM_ON_GRID / PANEL_ON_GRID |
| **Capabilities** | Real-time per-circuit watts, relay control (open/close), load shedding |

**Main meter lifetime:**

| Metric | Value |
|--------|-------|
| Main meter — consumed | 19,327 kWh |
| Main meter — produced | 6,089 kWh |
| Feedthrough — produced | 22,403 kWh |
| Feedthrough — consumed | 3,992 kWh |

### Circuit Map

| Circuit Name | Tabs | Voltage | Notes |
|--------------|------|---------|-------|
| Master bedroom | 1 | 120V | |
| Dryer not dryer | 2, 4 | 240V | ⚠️ Label inaccurate — needs verification |
| Bedroom 2-3-4 | 3 | 120V | All upstairs bedrooms |
| AC condenser 2 | 5, 7 | 240V | Secondary AC unit |
| Downstairs AC not sure | 6 | 120V | ⚠️ Label uncertain — needs verification |
| Air handler #2 | 8 | 120V | Upstairs HVAC air handler |
| Oven | 9, 11 | 240V | |
| Garage 15W | 10 | 120V | |
| Office Front | 12 | 120V | |
| AC condenser 1 | 13, 15 | 240V | Primary AC unit |
| Entry Hallway Dining | 14 | 120V | |
| Patio / Kitchen GFCI | 16 | 120V | |
| Dishwasher / Disposal | 17 | 120V | |
| Washer / Landscape | 18 | 120V | Clothes washer + landscape lighting |
| Unknown | 19 | 120V | ⚠️ **Needs identification** |
| CyberTruck 220v not used | 20, 22 | 240V | Wired but inactive — spare EV circuit |
| Master bathroom | 21 | 120V | |
| Microwave oven | 23 | 120V | |
| Int Garage grey | 24 | 120V | Interior garage |
| Pool sub panel | 25, 27 | 240V | Feeds Pentair pool equipment |
| Other EV charger | 26, 28 | 240V | Tesla Universal Wall Connector |

**Circuit label audit needed:** "Dryer not dryer", "Downstairs AC not sure", and "Unknown" (tab 19) need physical verification.

---

## 🏊 Pool: Pentair IntelliCenter

| Detail | Value |
|--------|-------|
| **Controller** | Pentair IntelliCenter |
| **LAN IP** | 192.168.68.91 (`pentair.local`) |
| **Ports** | 6681 (TCP), 6680 (WebSocket) |
| **Panel circuit** | "Pool sub panel" (tabs 25, 27 — 240V) |
| **Auth** | None |
| **Typical draw** | ~1.5 kW (~31% of nighttime house load) |

**Controls:** Pool pump (variable speed, RPM adjustable), spa, heater, lights, and automation circuits. Communicates via raw TCP protocol. The pool sub-panel draws from a dedicated 240V breaker on the SPAN panel.

---

## 🌡 Climate: Nest Thermostats

| Detail | Value |
|--------|-------|
| **Units** | 2 — Downstairs + Loft (upstairs) |
| **API** | Google Smart Device Management (SDM) |
| **Project ID** | edc12ede-0076-42d4-86d8-c87f49aec4b4 |
| **Auth** | OAuth2 (auto-refreshing JWT) |
| **Current mode** | Both COOLING |
| **Data available** | Temperature, humidity, setpoint, mode, HVAC state, occupancy |

**HVAC zones:**
- **Downstairs** thermostat → AC condenser 1 (tabs 13, 15) + air handler
- **Loft/Upstairs** thermostat → AC condenser 2 (tabs 5, 7) + air handler #2 (tab 8)

---

## 🌿 Irrigation: Orbit B-Hyve

| Detail | Value |
|--------|-------|
| **Controller** | Orbit B-Hyve |
| **LAN IP** | 192.168.68.66 |
| **API** | Cloud only (api.orbitbhyve.com) — no local control |
| **Panel circuit** | "Washer / Landscape" (tab 18, shared) |

Weather-adjusted smart scheduling. Powered from the landscape circuit shared with the washing machine.

---

## 📹 Security Cameras

### Wyze Cameras

| Camera | MAC | Location |
|--------|-----|----------|
| Front Side | D03F275A9799 | Exterior — side of house |
| Upstairs | 2CAA8E813AE9 | Interior — upstairs |
| Downstairs | 2CAA8E813B36 | Interior — downstairs |

**API:** Wyze cloud (wyze-sdk 2.2.0). Status and motion events only — **no snapshot capability** in current SDK version.

### Ring Doorbell

- **Status:** Invited (`jarvis.is.my.coo@gmail.com`) — integration pending
- 14-day acceptance window (received Feb 23, 2026)

---

## 📊 Observed Power Snapshot

*From a nighttime observation:*

| Source | Power |
|--------|-------|
| Grid import | 4.89 kW |
| Enphase solar | 0 W |
| SolarEdge solar | 2 W |
| Home panel total | 4.87 kW |
| Pool sub-panel | 1.51 kW |
| Cybertruck | Idle |
| Gateway mode | On-grid |

**Analysis:** Solar offline (night). Entire load from SRP grid. Pool is ~31% of total draw — significant overnight base load from pump scheduling.

---

## 🔌 Network Topology

All energy devices on LAN (192.168.68.x via TP-Link Deco mesh):

| Device | IP | Protocol | Auth | Local | Cloud | Writable |
|--------|-----|----------|------|-------|-------|----------|
| SPAN Panel | .93 | HTTP | Bearer token | ✅ | ✅ | ✅ |
| Enphase Gateway | .63 | HTTPS | JWT | ✅ | ✅ | Read-only |
| SolarEdge Inverter | — | — | — | ❌ | ✅ | Read-only |
| Tesla Gateway 3 | .86 | Fleet API | OAuth | ❌ | ✅ | Limited |
| Tesla Wall Connector | .87 | HTTP | None | ✅ | ✅ | ✅ |
| Pentair IntelliCenter | .91 | TCP :6681 | None | ✅ | ❌ | ✅ |
| Orbit B-Hyve | .66 | Cloud API | Email/pass | ❌ | ✅ | ✅ |
| Nest Thermostats | — | Google SDM | OAuth | ❌ | ✅ | Limited |
| Wyze Cameras | — | Cloud API | API key | ❌ | ✅ | Read-only |

---

## 🤖 Monitoring: Jarvis Home Energy OS

| Detail | Value |
|--------|-------|
| **Dashboard** | http://192.168.68.72:8793 |
| **Runtime** | Flask app on omen-claw |
| **Source** | `/home/rob/.openclaw/workspace/jarvis-home-energy/app.py` |
| **Poll interval** | 5 seconds |
| **Config** | `jarvis-home-energy/config.py` (credentials + device IPs) |

**Capabilities:**
- Real-time power flow visualization (solar → grid → load)
- Per-circuit power draw from SPAN
- EV charging status and session energy
- Pool equipment status
- Thermostat readings (temp, humidity, HVAC state)
- Camera status and motion events
- SSE (Server-Sent Events) for live browser updates

---

## 🔄 Automation Capabilities

### Controllable Loads
- **Pool pump** — RPM, on/off, scheduling (via Pentair)
- **EV charging rate** — start/stop, current limit (via Wall Connector)
- **SPAN breakers** — open/close any circuit remotely
- **HVAC setpoints** — temperature targets (via Nest SDM)
- **Irrigation** — zone control, scheduling (via B-Hyve cloud)

### Observable Sources
- **Solar production** — two independent systems (Enphase local + SolarEdge cloud)
- **Grid flow** — import/export via SPAN
- **Circuit-level consumption** — all 21 circuits via SPAN
- **EV charging** — real-time watts, session energy, vehicle connected state
- **Pool draw** — via SPAN circuit + Pentair status
- **Climate** — indoor temp/humidity, HVAC state, occupancy

---

## 🔧 Maintenance & Token Expiry

| Item | Status | Action |
|------|--------|--------|
| Enphase JWT | Expires ~March 2027 | Refresh via Enphase cloud portal |
| SPAN token | Long-lived (no expiry) | Re-register if factory reset (door open, press button 3×) |
| Tesla Fleet API | Auto-refreshes via `teslapy` | No action needed |
| Nest OAuth | Auto-refreshes | No action needed |
| SolarEdge local API | Not enabled | Enable admin access for local polling (future) |
| Circuit labels | 3 uncertain | Physical verification needed |
| Ring integration | Pending invite acceptance | Accept within 14-day window |
| SRP API | Not configured | Future: utility rate + usage polling |

---

## 📐 Physical Architecture

```
SRP Grid (utility meter)
    ↕
Tesla Gateway 3 (grid management, backup switching — NO BATTERY)
    ↕
SPAN Smart Panel (28 tabs / 21 circuits, per-circuit monitoring + control)
    ├── AC condenser 1 (240V, tabs 13+15) ←→ Downstairs Nest thermostat
    ├── AC condenser 2 (240V, tabs 5+7)   ←→ Loft Nest thermostat
    ├── Air handler #2 (tab 8)
    ├── Oven (240V, tabs 9+11)
    ├── Dryer circuit (240V, tabs 2+4)
    ├── EV charger — Wall Connector (240V, tabs 26+28, 48A)
    ├── CyberTruck circuit (240V, tabs 20+22, inactive)
    ├── Pool sub-panel (240V, tabs 25+27) → Pentair IntelliCenter
    │     ├── Pool pump (variable speed)
    │     ├── Spa
    │     ├── Heater
    │     └── Lights
    ├── Washer / Landscape (tab 18) → B-Hyve sprinkler controller
    ├── Kitchen circuits (microwave, dishwasher, GFCI)
    ├── Bedroom circuits (master, 2-3-4)
    ├── Office, entry, hallway, dining
    ├── Garage circuits (×2)
    └── Master bathroom

Solar feeds upstream into gateway/panel:
    • Enphase array (~6 kW) — 20 × IQ microinverters (part 800-01374-r02) → IQ Gateway
    • SolarEdge array (~5.8 kWp) — SE5000H-US string inverter
    Combined: ~11.8 kW total solar capacity

NO BATTERY STORAGE — solar excess goes to grid via net metering
```
