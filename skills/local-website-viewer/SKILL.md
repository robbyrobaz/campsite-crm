# Local Website Viewer Skill

View and screenshot local websites running on your machine.

## Usage

```bash
# Take screenshot of a local website
jarvis_view_website http://localhost:8888/blofin-dashboard.html

# Or in tools, use the view_local_website.sh script
./view_local_website.sh http://localhost:8080/some-page

# Returns: screenshot.png + rendered text content
```

## What It Does

1. Takes a screenshot of the specified local URL using headless Chrome
2. Extracts visible text content from the page
3. Returns both the image and text so you can see exactly what the user sees

## Why This Matters

Never claim a website is fixed without actually looking at it. This skill provides visibility into local dashboards and web apps.

## Files

- `view_local_website.sh` - Main script using Chromium headless mode
- `extract_visible_text.js` - Node script to extract rendered text from DOM

## Requirements

- Chromium or Chrome installed
- Node.js (for text extraction)
