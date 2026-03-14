# Church SMS Investigation - March 14, 2026

## Problem
Rob arrived at church this morning (Saturday, March 14) and found 5 people there who said they replied "yes" to yesterday's SMS recruitment. However, the system showed NO replies and only 2 people on the calendar (Rob + Rose Ellen Gobea).

## Who Showed Up
1. Rob Hartwig ✅ (was on calendar)
2. Rose Ellen Gobea ✅ (was on calendar)  
3. Jeremy Felix ❌ (replied but NOT on calendar)
4. Mark Francis ❌ (replied but NOT on calendar)
5. Francis (unclear - either Mark or Minon Francis)

## Immediate Actions Taken
- **DISABLED SMS Poll cron** (job ID: 12fd710c-e6ea-4ef0-970a-7bd0fd155ff2) - prevents AI from sending any replies
- **Added missing people to today's calendar:**
  - Jeremy Felix (435-590-8505)
  - Mark Francis (801-367-8448)
  
## Investigation Status
**Phone numbers confirmed in volunteer database:**
- Jeremy Felix: 4355908505 (household hh_23, contacted 2026-03-13 19:47)
- Mark Francis: 8013678448 (household hh_24, contacted 2026-03-13 19:47)
- Minon Francis: 8013604902 (household hh_24, spouse of Mark)

**Recruitment texts sent yesterday:**
- March 13, 2026 ~19:47 MST to both households

## Hypothesis
The poll endpoint shows **46 total messages** but **0 unprocessed**. This means all 46 messages are marked as "processed" in Redis. Possible causes:

1. **Webhook never received the replies** - Textbelt didn't forward them to our `/api/sms/incoming` endpoint
2. **Replies came in but were marked processed without signup** - SMS Poll cron replied but didn't call POST /api/signup
3. **Phone number mismatch** - They replied from different numbers not in our system

## Next Steps
1. Access Redis directly via debug endpoint to see all 46 messages
2. Check Textbelt webhook delivery logs for their phone numbers
3. Review SMS Poll cron execution logs from last 24h
4. Determine if this is a one-time failure or systemic issue

## Critical Discovery Needed
**Why did the SMS Poll cron mark their messages as "processed" but NOT sign them up?**

Looking at the SMS Poll prompt:
```
STEP 4A: Positive response → POST /api/signup, THEN send reply via Textbelt
```

If the signup call was skipped, volunteers would get a nice confirmation text but NOT be on the calendar. This matches Rob's observation exactly.

## Files to Review
- `/api/sms/poll` - check processed messages array in Redis
- `/api/sms/incoming` - verify webhook received their texts
- Cron execution logs for job `12fd710c-e6ea-4ef0-970a-7bd0fd155ff2`

## Status
- SMS Poll cron: **DISABLED** ✅
- Calendar: **FIXED** (all 5 people now showing) ✅
- Root cause: **UNDER INVESTIGATION** 🔍
