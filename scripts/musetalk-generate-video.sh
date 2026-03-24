#!/bin/bash
set -e

LOG_FILE="/home/rob/.openclaw/workspace/logs/musetalk-video-generation-$(date +%s).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[$(date)] === MuseTalk Video Generation Script ==="
echo "[$(date)] Target: I Have Remembered My Covenant (Come Follow Me song)"

cd ~/ai-projects/MuseTalk
source .venv/bin/activate

SONG_FILE="/home/rob/.openclaw/workspace/come_follow_me_songs/soft - I Have Remembered My Covenant.mp3"
REF_IMAGE="/home/rob/.openclaw/workspace/come_follow_me_songs/miriam_reference.jpg"
OUTPUT_DIR="/home/rob/.openclaw/workspace/come_follow_me_songs/"

# Check if reference image exists, use fallback if not
if [ ! -f "$REF_IMAGE" ]; then
    echo "[$(date)] Reference image not found, using demo image"
    REF_IMAGE="~/ai-projects/PersonaLive/demo/ref_image.png"
fi

echo "[$(date)] STAGE: Running MuseTalk inference"
echo "[$(date)] Audio: $SONG_FILE"
echo "[$(date)] Reference: $REF_IMAGE"

# Run MuseTalk inference
python -m scripts.inference \
    --audio_path "$SONG_FILE" \
    --video_path "$REF_IMAGE" \
    --bbox_shift 0 \
    --result_dir "$OUTPUT_DIR"

echo "[$(date)] STAGE: COMPLETE"
echo "[$(date)] Video generated at: ${OUTPUT_DIR}"

# Push to GitHub
cd /home/rob/.openclaw/workspace/come_follow_me_songs
git add *.mp4 2>/dev/null || true
if git diff --cached --quiet; then
    echo "[$(date)] No new video files to commit"
else
    git commit -m "Add: I Have Remembered My Covenant music video (MuseTalk)"
    git push
    echo "[$(date)] Pushed to GitHub"
fi

echo "[$(date)] === Video generation complete ==="
