#!/bin/bash
set -euo pipefail

# Local Website Viewer - Screenshot + text extraction
# Usage: ./view_local_website.sh <url> [output_dir]

URL="${1:-http://localhost:8080}"
OUTPUT_DIR="${2:-.}"

if [[ ! "$URL" =~ ^https?:// ]]; then
  URL="http://$URL"
fi

FILENAME=$(echo "$URL" | sed 's|[^a-zA-Z0-9]|_|g' | head -c 50)
SCREENSHOT="$OUTPUT_DIR/${FILENAME}_screenshot.png"
TEXTFILE="$OUTPUT_DIR/${FILENAME}_text.txt"

echo "📸 Capturing: $URL"
echo "  → Screenshot: $SCREENSHOT"
echo "  → Text: $TEXTFILE"

# Take screenshot using chromium headless
if command -v chromium-browser &> /dev/null; then
  CHROME_BIN="chromium-browser"
elif command -v chromium &> /dev/null; then
  CHROME_BIN="chromium"
elif command -v google-chrome &> /dev/null; then
  CHROME_BIN="google-chrome"
else
  echo "❌ No Chromium/Chrome found. Install: sudo apt install chromium-browser"
  exit 1
fi

$CHROME_BIN \
  --headless \
  --disable-gpu \
  --screenshot="$SCREENSHOT" \
  --window-size=1920,1080 \
  "$URL" 2>/dev/null || {
  echo "❌ Failed to screenshot. Is the URL accessible?"
  exit 1
}

echo "✓ Screenshot saved"

# Extract visible text using a simple HTML parser + Node
node <<'EOF' > "$TEXTFILE" 2>/dev/null || {
  echo "⚠️  Text extraction skipped (Node not available)"
}
const http = require('http');
const https = require('https');
const url = process.argv[1];
const isHttps = url.startsWith('https');
const protocol = isHttps ? https : http;

protocol.get(url, (res) => {
  let html = '';
  res.on('data', chunk => html += chunk);
  res.on('end', () => {
    // Very simple: remove script/style, decode entities, extract text
    html = html
      .replace(/<script[^>]*>.*?<\/script>/gis, '')
      .replace(/<style[^>]*>.*?<\/style>/gis, '')
      .replace(/<[^>]+>/g, '\n')
      .replace(/\n\n+/g, '\n')
      .trim();
    console.log(html);
  });
}).on('error', (e) => {
  console.error('Error:', e.message);
  process.exit(1);
});
EOF
"$URL"

echo "✓ Visible text extracted"
echo ""
echo "📊 Page Summary:"
echo "  URL: $URL"
echo "  Screenshot: $(ls -lh "$SCREENSHOT" | awk '{print $5}')"
echo "  Text lines: $(wc -l < "$TEXTFILE")"
echo ""
echo "Opening screenshot..."
if command -v feh &> /dev/null; then
  feh "$SCREENSHOT" 2>/dev/null &
elif command -v display &> /dev/null; then
  display "$SCREENSHOT" 2>/dev/null &
else
  echo "⚠️  To view: open $SCREENSHOT"
fi

echo "✓ Done"
