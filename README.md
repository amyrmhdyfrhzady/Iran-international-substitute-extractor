# Iran International Live Subtitle API

Python + Playwright + OpenCV + Tesseract Persian OCR. No AI.

The worker opens `https://ott.iranintl.com/tv?lang=fa`, captures the video continuously, cheaply detects changes in the CapitalNews area, and sends only changed frames to a FIFO OCR queue.

## News layouts

- **Mode 1:** CapitalNews is near the bottom. Only CapitalNews is extracted.
- **Mode 2:** CapitalNews is in the middle/lower-middle and TextNews is at the bottom. Both are extracted.
- **Mode 3 / anything else:** nothing is extracted.

The primary layout gate is CapitalNews: a white rectangular area with **red text**. White with black text is intentionally rejected.

The coordinates are normalized to the video frame, so the worker is independent of the exact browser size.

## JSON API

The current file is:

`api/news.json`

After the repository is public, it can be consumed directly from GitHub's raw file URL:

`https://raw.githubusercontent.com/OWNER/REPO/main/api/news.json`

The JSON is ordered newest hour first.

Example shape:

```json
{
  "updated_at": "2026-09-18T15:42:10+03:30",
  "timezone": "Asia/Tehran",
  "hours": [
    {
      "time": "15:00",
      "day": "18 September 2026",
      "CapitalNews": ["..."],
      "TextNews": ["..."]
    },
    {
      "time": "14:00",
      "day": "18 September 2026",
      "CapitalNews": ["..."],
      "TextNews": ["..."]
    }
  ]
}
```

A story can appear again in a later hour. It is not globally deduplicated across hours. Inside the same hour, exact/near-exact repeats are ignored.

## Configuration

Edit `config.json`.

The default regions are normalized from the four supplied screenshots. They are a first-pass detector and are intentionally easy to tune in `config.json` during debugging.

## Local debug

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -m src.main --debug-once
```

The debug run writes `debug/video-frame.png` and `debug/video-info.json`.

Then run:

```bash
python -m src.main --once
```

## GitHub Actions

The workflow uses a GitHub-hosted Ubuntu runner for a maximum ~4h50m worker. A five-hour schedule starts another run. The public repository gets free standard GitHub-hosted runner usage.

The workflow commits `api/news.json` back to the repository whenever the JSON changes.

If GitHub asks, enable Actions for the repository.

