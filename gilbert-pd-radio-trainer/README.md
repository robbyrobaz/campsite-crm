# Gilbert PD Radio Trainer

A lightweight training app for radio-code memorization with:

- Teach mode (searchable flashcard grid)
- Quiz mode (multiple-choice + streak tracking)
- Speed Drill mode (60-second challenge)
- Flashcard mode (flip cards, reveal meaning, shuffle)
- Manage mode (add code, import/export JSON)
- Local progress persistence in browser storage

## Run

```bash
cd /home/rob/.openclaw/workspace/gilbert-pd-radio-trainer
python3 -m http.server 8081
```

Open: <http://127.0.0.1:8081>

## Official dataset

`index.html` automatically loads `data/gilbert-official-codes.json` on first run. That file contains the December 2023 Gilbert Police Department code sheet broken into the `series` groups you provided, so the Teach/Quiz/Drill flows are already working with the real list (with `category` taken from each series name). If something looks off you can reimport the same JSON under Manage → Import.

## Code list format

### Array shorthand
Import JSON as an array of objects if you want to build a smaller custom set or quick experiment:

```json
[
  { "code": "10-4", "meaning": "Acknowledged", "category": "Ten-Code" }
]
```

### Official Gilbert JSON
For full fidelity, upload the original Gilbert PD payload (object with `series`). The trainer now understands that format and creates `category` tags automatically from each `series.name` so the import does not require extra preprocessing.

```json
{
  "series": [
    {
      "name": "10-Codes",
      "codes": [
        { "code": "10-4", "meaning": "Acknowledged" }
      ]
    }
  ]
}
```

If the official dataset fetch fails (e.g., you are offline), the app still falls back to `data/starter-codes.json` so nothing breaks.

## Important

The included starter list remains generic training content. Use `data/gilbert-official-codes.json` or your own Gilbert PD import for exact policy alignment.
