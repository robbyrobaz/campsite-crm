#!/bin/bash
# One-shot NQ FT check reminder — fires at 10:48 AM MST Mar 6 2026
curl -s -X POST \
  -H "Title: NQ Forward Test Check Due" \
  -H "Priority: high" \
  -H "Tags: chart_with_upwards_trend" \
  -d "Check if atr_breakout/micro_pullback/failed_breakout/session_open_drive/vwap_stretch/orb/break_retest_815/eight_am_break_retest started generating FT trades after threshold fix. Query paper_trades in nq_pipeline.db." \
  https://ntfy.sh/nq-pipeline

# Self-destruct this timer after firing
systemctl --user disable --now nq-ft-reminder.timer
rm -f ~/.config/systemd/user/nq-ft-reminder.{timer,service}
systemctl --user daemon-reload
