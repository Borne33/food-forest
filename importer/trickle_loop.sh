#!/bin/bash
# Slow use-data enrichment loop: ~25 PFAF + 50 NAEB fetches per hour, run
# SEQUENTIALLY (so the two sources never race on the same row's fields), gently
# paced, everything cached. Auto-stops after 2026-08-09 ("the next few days").
#
# Start:  setsid nohup bash /Users/alexbornemann/food-forest/importer/trickle_loop.sh >/dev/null 2>&1 &
# Stop:   pkill -f trickle_loop.sh
# Watch:  tail -f /Users/alexbornemann/food-forest/importer/trickle.log
cd /Users/alexbornemann/food-forest/importer || exit 1
PY=/usr/bin/python3
STOP=20260809
sleep 2700   # let the batch 2-5 backfill finish before enriching (avoid write overlap)
while [ "$(date +%Y%m%d)" -le "$STOP" ]; do
  start=$(date +%s)
  echo "===== $(date) PFAF 25 =====" >> trickle.log
  $PY pfaf_trickle.py --limit 25 --delay 72 >> trickle.log 2>&1
  echo "===== $(date) NAEB 50 =====" >> trickle.log
  $PY naeb_trickle.py --limit 50 --delay 36 >> trickle.log 2>&1
  el=$(( $(date +%s) - start ))
  s=$(( 3600 - el )); [ $s -lt 60 ] && s=60
  sleep $s
done
echo "===== $(date) trickle loop ended (past stop date $STOP) =====" >> trickle.log
