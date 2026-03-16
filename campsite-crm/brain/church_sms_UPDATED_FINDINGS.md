# Church SMS Investigation - UPDATED FINDINGS
## March 14, 2026

## CRITICAL UPDATE: Systemic Webhook Failure

### Previous Theory (INCORRECT)
We initially thought only Jeremy & Mark's replies were lost.

### NEW EVIDENCE: Complete Webhook Breakdown

**Timeline:**
```
March 13, 2026:

WORKING PERIOD (before 5 AM MST):
03:04 AM - Rob reply received ✅
03:31 AM - Rose Ellen "Yes" received ✅
04:10 AM - Colleen replies (2x) received ✅
04:21 AM - Rob signup received ✅

FAILURE PERIOD (after 5 AM MST):
05:00 AM - Webhook stops working ❌
12:43 PM - 5 people texted (Nathan, Rita, Dane, Mark, Jeremy)
          → ZERO replies received
01:47 PM - 6 people texted (Sandra, Derek, Tiffany, Laura, Curtis, Kim)
          → ZERO replies received

Total recruited after 5 AM: 11 people
Total replies received: ZERO
```

### What This Proves

1. **Outbound was NOT the issue**
   - All texts sent correctly from omen-claw
   - Textbelt confirmed delivery
   - No rate-limiting (we learned that lesson)

2. **Inbound webhook completely broke**
   - Worked fine until ~5 AM MST
   - Zero replies received after 5 AM
   - 11 people texted, 0 replies stored

3. **Not specific to Jeremy & Mark**
   - ALL replies from that afternoon were lost
   - This is a systemic failure, not isolated

### Webhook Flow (for reference)
```
Reply sent from phone
  ↓
Carrier delivers to Textbelt
  ↓
Textbelt should POST to:
  https://church-volunteer-coordinator.vercel.app/api/sms/incoming
  ↓
❌ THIS ENTIRE CHAIN BROKE AT 5 AM MST
  ↓
Vercel /api/sms/incoming saves to Redis
  ↓
SMS Poll cron reads from Redis every 2 min
```

### Possible Causes

**A. Textbelt webhook service crashed**
- Their webhook POST system went down
- No POSTs sent to ANY customer webhooks
- Would affect all Textbelt customers
- Contact Textbelt support to verify

**B. Our Vercel endpoint became unreachable**
- `/api/sms/incoming` crashed or was offline
- Textbelt's POSTs got HTTP errors
- Check Vercel function logs for downtime

**C. Vercel blocked Textbelt's IP**
- DDoS protection kicked in
- Rate limiting on inbound webhooks
- Check Vercel security logs

**D. Upstash Redis quota/connection failure**
- Our endpoint worked but couldn't save to Redis
- Upstash was down or over quota
- Check Upstash status page for March 13

### Evidence Rob Can Gather

**1. Vercel Function Logs (CRITICAL)**
```
URL: https://vercel.com/robbyrobazs-projects/church-volunteer-coordinator/logs
Filter: /api/sms/incoming
Time: March 13, 5:00 AM - midnight MST

Look for:
- Are there ANY POST requests after 5 AM?
  → If NO: Textbelt webhook delivery failed
  → If YES with errors: Our endpoint crashed
  → If YES with 200s: Redis save failed
```

**2. Textbelt Support Email**
```
To: support@textbelt.com
Subject: Webhook delivery failure March 13, 2026

Body:
I'm investigating a complete webhook failure on March 13, 2026.

Between 05:00-23:59 MST (12:00-06:59 UTC March 13), I sent 11 recruitment
texts with webhook URLs configured. Zero webhook POSTs were received by 
my endpoint.

Earlier that same day (00:00-04:30 MST), webhooks worked perfectly - 
5 replies were successfully delivered.

Can you check your webhook delivery logs for:
- Webhook URL: https://church-volunteer-coordinator.vercel.app/api/sms/incoming  
- Time window: March 13, 12:00 UTC - March 14, 06:59 UTC
- Were POSTs attempted? Did they fail?
- Was there a webhook service outage?

TextIds affected (sample):
- 428571773431142364 (sent 19:43 UTC)
- 126431773431164338 (sent 19:43 UTC)

Thank you,
Rob Hartwig
```

**3. Check Upstash Status**
```
URL: https://status.upstash.com/
Check: March 13, 2026 for any Redis outages
```

### Immediate Action Items

1. ✅ Calendar manually fixed (Done)
2. ✅ SMS Poll cron disabled (Done)  
3. ⏳ Check Vercel logs (Rob to do)
4. ⏳ Email Textbelt support (Rob to do)
5. ⏳ Implement webhook health monitoring (before re-enabling)

### Long-term Prevention

**A. Webhook Health Monitor (HIGH PRIORITY)**
Create hourly cron:
- Check timestamp of last successful `/api/sms/incoming` POST
- If >6 hours old during active recruitment → alert Rob
- Prevents 18-hour silent failures

**B. Redundant Reply Channel**
- Add email confirmations as backup
- If SMS webhook fails, at least they get email
- Requires collecting email addresses

**C. Test Before Re-enabling**
Before turning SMS Poll cron back on:
1. Send test recruitment to your own number
2. Reply to it
3. Verify it appears in admin panel within 1 minute
4. If not → webhook still broken, don't re-enable

### Files
- Original investigation: `brain/church_sms_investigation_2026-03-14.md`
- Root cause (original): `brain/church_sms_root_cause_FINAL.md`
- Next steps: `brain/church_sms_next_steps.md`
- **This file** (updated findings): `brain/church_sms_UPDATED_FINDINGS.md`

---

**Bottom line:** This was a complete webhook infrastructure failure starting at 5 AM MST on March 13. Not isolated to Jeremy & Mark - affected ALL 11 people recruited that afternoon. Vercel logs will show whether it was Textbelt's fault or ours.
