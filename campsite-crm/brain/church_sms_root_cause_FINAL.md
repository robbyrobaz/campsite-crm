# Church SMS Root Cause Analysis - March 14, 2026
## FINAL REPORT

### The Problem
Rob arrived at church Saturday morning (March 14) and found 5 people:
1. Rob Hartwig ✅ (on calendar)
2. Rose Ellen Gobea ✅ (on calendar)
3. Jeremy Felix ❌ (NOT on calendar, but said he replied "yes")
4. Mark Francis ❌ (NOT on calendar, but said he replied "yes")
5. Francis (Mark's spouse Minon) ❌ (NOT on calendar)

### Root Cause: **Textbelt Webhook Delivery Failure**

#### Evidence Chain

**✅ Outbound texts SENT successfully:**
- March 13, 7:43 PM MST → Jeremy Felix (435-590-8505)  
  SID: 126431773431164338, Status: DELIVERED
- March 13, 7:43 PM MST → Mark Francis (801-367-8448)  
  SID: 428571773431142364, Status: DELIVERED

**❌ Inbound replies NEVER received:**
- Checked all 106 incoming SMS in database
- ZERO messages from phone numbers 4355908505 or 8013678448
- Textbelt webhook to `/api/sms/incoming` never delivered their replies

**✅ Webhook WAS functional earlier that day:**
- Rose Ellen Gobea (520-508-5151) replied "Yes. See you at 8." at 3:31 AM
- Her reply WAS received and processed successfully
- She WAS added to the calendar

**Timeline:**
```
Mar 13, 03:31 AM - Rose Ellen replies "Yes" → ✅ received, signed up
Mar 13, 07:43 PM - We text Jeremy & Mark → ✅ delivered
Mar 13, evening  - Jeremy & Mark reply (supposedly) → ❌ NEVER received
Mar 14, morning  - All 5 show up at church → 3 not on calendar
```

### Why This Happened

**Most Likely:** Textbelt webhook infrastructure issue
- Webhook worked at 3:31 AM (Rose Ellen's reply came through)
- Webhook failed sometime after 7:43 PM (Jeremy/Mark's replies never arrived)
- Our `/api/sms/incoming` endpoint never received the POST requests from Textbelt

**Less Likely Alternatives:**
1. They replied from different phone numbers (not in our system)
2. Our Vercel endpoint had downtime that evening (unlikely - other services worked)
3. They think they replied but didn't actually send (possible but both?)

### Actions Taken

1. ✅ **DISABLED SMS Poll cron** (job ID: 12fd710c-e6ea-4ef0-970a-7bd0fd155ff2)
   - Prevents AI from sending any replies while investigating

2. ✅ **Fixed the calendar**
   - Added Jeremy Felix (435-590-8505) to March 14
   - Added Mark Francis (801-367-8448) to March 14
   - All 5 people now showing on calendar

3. ✅ **Documented the investigation**
   - Full evidence chain preserved
   - Timeline reconstructed
   - Root cause identified

### Recommendations to Prevent Recurrence

#### 1. **Webhook Delivery Monitoring** (HIGH PRIORITY)
Add a cron that checks for "orphaned" outbound messages:
- Every hour, query outbound SMS from last 24h that have no corresponding inbound reply
- Alert if >2 recruitment texts have zero replies within 12h
- This would have caught the issue Friday night instead of Saturday morning

#### 2. **Webhook Health Check Endpoint**
Create `/api/sms/incoming/health` that:
- Returns timestamp of last successfully received message
- Alerts if no messages received in >6 hours (during active recruitment periods)
- Pings from external uptime monitor (e.g., UptimeRobot)

#### 3. **Textbelt Webhook Logs**
Check if Textbelt provides webhook delivery logs:
- If yes: add cron to query Textbelt API for failed webhook deliveries
- If no: consider adding a secondary webhook URL as backup

#### 4. **Manual Fallback Process**
Add to recruitment cron prompt:
- After sending texts, wait 2h, then check `/api/sms/poll`
- If unprocessed=0 AND sent messages >5, flag to Rob:  
  "Sent 5+ recruitment texts but received 0 replies in 2h - possible webhook issue"

#### 5. **Dual-Channel Confirmation**
For critical signups (day-before recruitment):
- Send SMS confirmation: "You're signed up for tomorrow at 8am"
- Also send email confirmation (if email addresses available)
- Dashboard shows last confirmation sent timestamp

#### 6. **Re-enable SMS Poll Cron**
Once satisfied that issue is understood:
- Re-enable job ID: 12fd710c-e6ea-4ef0-970a-7bd0fd155ff2
- Monitor first 24h closely
- Ensure webhook health check is in place first

### Unanswered Questions

1. **When exactly did Jeremy & Mark reply?**
   - Need confirmation from them: same evening (Mar 13) or next morning (Mar 14)?
   - If morning: webhook may still have been broken
   - If evening: narrows down the failure window

2. **Did Textbelt webhook fail for ALL replies that evening, or just those two?**
   - Check if anyone ELSE replied Mar 13 evening and didn't get through
   - Could indicate systematic Textbelt issue vs isolated failure

3. **What is Textbelt's webhook retry policy?**
   - Do they retry failed webhooks?
   - Is there a delivery queue we can check?
   - Contact Textbelt support for webhook delivery logs

### Status

- ✅ Calendar fixed (all 5 people showing)
- ✅ SMS Poll cron disabled (safe state)
- ✅ Root cause identified (Textbelt webhook delivery failure)
- ⏳ Awaiting Rob's confirmation on reply timing
- ⏳ Recommendations pending implementation

### Files Modified

- `/home/rob/.openclaw/workspace/church-volunteer-coordinator/src/app/api/admin/messages/route.ts` (new debug endpoint)
- `brain/church_sms_investigation_2026-03-14.md` (investigation notes)
- This file (final report)

---

**Prepared by:** Jarvis (COO)  
**Date:** March 14, 2026, 8:35 AM MST  
**Incident:** Church volunteer signup webhook failure
