# SRP E-27 Customer Generation Price Plan — Accurate Documentation

**Plan Code:** E-27  
**Plan Name:** Customer Generation Price Plan  
**Utility:** Salt River Project (SRP)  
**Location:** Queen Creek, Arizona  
**Timezone:** MST (no daylight savings)  
**Last Updated:** 2026-03-15 (FINAL CORRECTED VERSION)

---

## Core Billing Rule

**Monthly demand charge is determined by the highest 30-minute average kW measured during ON-PEAK hours within the billing cycle.**

This is a **demand-based rate plan**. Your bill has:
1. **Energy charges** (kWh consumed)
2. **Demand charges** (highest 30-min avg kW during on-peak)

**Objective:** Minimize peak kW during on-peak hours.

---

## Three Seasonal Rate Structures

### WINTER
**Billing Cycle Months:** November, December, January, February, March, April

**ON-PEAK (Monday–Friday only):**
- **05:00–09:00** (5 AM – 9 AM)
- **17:00–21:00** (5 PM – 9 PM)

**OFF-PEAK:** All other times

---

### SUMMER
**Billing Cycle Months:** May, June, September, October

**ON-PEAK (Monday–Friday only):**
- **14:00–20:00** (2 PM – 8 PM)

**OFF-PEAK:** All other times

---

### SUMMER PEAK
**Billing Cycle Months:** July, August

**ON-PEAK (Monday–Friday only):**
- **14:00–20:00** (2 PM – 8 PM)

**OFF-PEAK:** All other times

*(Same hours as Summer, but higher demand rates)*

---

## Weekend Rule

**Saturday & Sunday:** Off-peak all day (no on-peak hours)

---

## Holiday Rule

**SRP Holidays** (on-peak disabled):
- New Year's Day
- Memorial Day
- Independence Day
- Labor Day
- Thanksgiving Day
- Christmas Day

---

## Current Context

**Current Date:** 2026-03-15 (Sunday)  
**Current Season:** WINTER (Nov–Apr)

**Weekday Peak Windows (if Monday-Friday):**
- 05:00–09:00 (morning rush)
- 17:00–21:00 (evening rush)

**Today's Status:**
- **Sunday** → **No peak hours today**

**Next Schedule Change:** May 1, 2026  
**New Season:** SUMMER  
**New Peak Window:** 14:00–20:00 (weekdays)

---

## Load Management Policy

### High-Load Devices (Demand Risk)
- EV charger (Tesla Wall Connector, up to 11.5 kW)
- Pool pump (~1.5 kW)
- Electric dryer (~5.4 kW)
- Electric oven (~3.5 kW)
- Dishwasher heat-dry cycle
- Water heater
- Large compute rigs / GPU mining
- Multiple HVAC compressors running together

### Rules
1. **Do NOT start high loads during on-peak**
2. **Prevent multiple high loads simultaneously during on-peak**
3. **Prioritize solar self-consumption midday** (09:00-15:00)
4. **Shift flexible loads to off-peak**

---

## Solar Optimization

**Preferred heavy-load window:** 09:00–15:00

**Run these during solar hours:**
- EV charging
- Pool pump operation
- Laundry (washer + dryer)
- Dishwasher
- Compute jobs

**Reason:** Use solar first, then off-peak grid, avoid on-peak demand spikes.

---

## Jarvis Automation

### During ON-PEAK
- ❌ Do NOT start EV charging
- ❌ Do NOT start pool pump (unless critical)
- ❌ Avoid oven + dryer overlap
- ❌ Avoid dishwasher heat-dry
- ❌ Prevent multiple large loads at once
- ⚠️ Throttle non-critical compute
- 🎯 Keep total house kW low

### During OFF-PEAK
- ✅ Normal operation allowed
- ✅ Preferred time for deferred loads

---

## Season Summary

| Season | Months | Weekday On-Peak | Weekend |
|--------|--------|-----------------|---------|
| **Winter** | Nov–Apr | 05:00-09:00 & 17:00-21:00 | Off-peak all day |
| **Summer** | May, Jun, Sep, Oct | 14:00-20:00 | Off-peak all day |
| **Summer Peak** | Jul, Aug | 14:00-20:00 | Off-peak all day |

---

## References

- SRP E-27 Rate Schedule: https://srpnet.com/prices/pdfx/e27.pdf
- Internal: `HOME_POWER_SYSTEM.md` for device details
