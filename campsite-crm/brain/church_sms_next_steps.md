# Church SMS Investigation - Next Steps

## What We Know
1. ✅ We sent recruitment texts to Jeremy Felix & Mark Francis on March 13, 7:43 PM
2. ✅ Textbelt confirmed both messages were DELIVERED
3. ✅ They replied "yes" (according to them showing up at church)
4. ❌ Their replies NEVER appeared in our database
5. ✅ Webhook worked earlier that day (Rose Ellen's 3:31 AM reply came through)

## Root Cause
**Textbelt webhook delivery failure** - replies never reached our `/api/sms/incoming` endpoint.

## Why We Can't Query Replies via API
Text belt does **NOT** store replies. Their architecture:
- When someone replies → Textbelt receives SMS from carrier
- Textbelt immediately POSTs to your `replyWebhookUrl`
- If the POST fails, **the reply is lost** (no retry, no storage, no query API)

This is a fundamental limitation of Textbelt's webhook-only design.

## What Rob Can Do Now

### 1. Check Vercel Logs (5 minutes)
**URL:** https://vercel.com/robbyrobazs-projects/church-volunteer-coordinator/logs

**Filter:**
- Function: `/api/sms/incoming`
- Time: March 13, 7:00 PM - March 14, 8:00 AM MST

**Look for:**
```
✅ POST requests from Textbelt with fromNumber: "8013678448" or "4355908505"
   → If found: our endpoint received them but failed to save (code bug)
   
❌ NO POST requests at all
   → Textbelt webhook delivery failed
   
⚠️ 500 errors or crashes
   → Our endpoint was broken
```

### 2. Email Textbelt Support (10 minutes)
**To:** support@textbelt.com  
**Subject:** Webhook delivery verification request for textIds 428571773431142364, 126431773431164338

**Body:**
```
Hi Textbelt team,

I'm investigating missing SMS replies from March 13-14, 2026.

I sent two messages with webhook URLs configured:
- textId: 428571773431142364 (to 801-367-8448)
- textId: 126431773431164338 (to 435-590-8505)
- Webhook URL: https://church-volunteer-coordinator.vercel.app/api/sms/incoming

The recipients confirmed they replied to these messages, but our webhook 
endpoint never received the POSTs from Textbelt.

Questions:
1. Do you keep webhook delivery logs I can query?
2. Can you confirm whether replies were received for these textIds?
3. If so, were webhook POSTs attempted? Did they fail?
4. Do you have retry logic for failed webhooks?

Thank you,
Rob Hartwig
```

### 3. Ask Jeremy & Mark (2 minutes)
When you see them next:
- "Hey, when did you reply to my Saturday text? Same evening (Friday), or Saturday morning?"
- "Did you get a confirmation text back from me?"

This narrows down the failure window.

### 4. Implement Monitoring (Optional - 1 hour)
Prevent this from happening again:

**A. Orphaned Outbound Monitor**
Create a cron that runs every 6h:
- Query outbound SMS from last 24h that have `body` containing "church" or "Saturday"
- Check if corresponding inbound reply exists within 12h
- If >2 recruitment texts have zero replies → alert Rob via ntfy

**B. Webhook Health Endpoint**
Add `/api/sms/incoming/health`:
- Returns timestamp of last successfully received message
- External uptime monitor pings it hourly
- Alerts if last message >12h old during active periods

## What to Do About This Weekend

### Immediate Fix (Done ✅)
- Calendar updated with all 5 people
- SMS Poll cron disabled (safe state)

### Before Re-enabling SMS Poll
1. Review Vercel logs (see if there's a pattern)
2. Add webhook health monitoring
3. Test the flow:
   - Send yourself a test recruitment SMS
   - Reply to it
   - Verify it appears in admin panel within 1 minute
   - If not → debug before re-enabling

### Long-term Solution
Consider dual-channel delivery:
- Primary: SMS via Textbelt webhook
- Backup: Daily email digest ("You're signed up for tomorrow")
- If webhook fails, at least they get email confirmation

## Decision Point

**Re-enable SMS Poll cron?**
- ✅ Yes - if Vercel logs show webhook POSTs ARE arriving for other messages
- ❌ No - if logs show systemic webhook delivery failures
- ⏸️ Wait - until monitoring is in place

Current state: **SAFE** (cron disabled, calendar manually fixed)

## Files
- Full investigation: `brain/church_sms_investigation_2026-03-14.md`
- Root cause report: `brain/church_sms_root_cause_FINAL.md`
- This file: `brain/church_sms_next_steps.md`

---

**Status:** Waiting on Rob to check Vercel logs and/or contact Textbelt support.
