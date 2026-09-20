import argparse
import json
import logging
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from zoneinfo import ZoneInfo

from .browser import LiveBrowser
from .detector import LayoutDetector
from .ocr import OCR
from .queueing import FrameQueue, FrameChange
from .store import NewsStore

ROOT = Path(__file__).resolve().parents[1]
TEHRAN = ZoneInfo("Asia/Tehran")


def load_config(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def now_tehran():
    return datetime.now(TEHRAN)


def image_from_png(data):
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


class GitPublisher:
    def __init__(self, path):
        self.path = Path(path)
        self.last = time.monotonic() - 999
        self.interval = 20

    def publish(self, force=False):
        if not force and time.monotonic() - self.last < self.interval:
            return

        self.last = time.monotonic()

        try:
            subprocess.run(
                ["git", "config", "user.name", "github-actions[bot]"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "config",
                    "user.email",
                    "41898282+github-actions[bot]@users.noreply.github.com",
                ],
                check=True,
            )
            subprocess.run(["git", "add", str(self.path)], check=True)

            changed = subprocess.run(
                ["git", "diff", "--cached", "--quiet"]
            ).returncode != 0

            if not changed:
                return

            subprocess.run(
                ["git", "commit", "-m", "Update subtitle API"],
                check=True,
            )

            result = subprocess.run(
                ["git", "push"],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logging.warning("git push failed: %s", result.stderr.strip())

        except Exception as exc:
            logging.warning("Publish failed: %s", exc)


def capture_loop(browser, detector, frame_queue, stop, config, deadline):
    """
    Playwright's sync API is thread-bound.

    The browser/page is created on the main thread and ALL Playwright calls
    therefore stay on this same thread. Only decoded OpenCV frames are sent
    to the worker thread.
    """
    previous_capital = None
    previous_textnews = None
    last_layout = None
    last_hour_key = None

    threshold = float(config["change_threshold"])
    interval = float(config["capture_interval_seconds"])

    while not stop.is_set() and time.monotonic() < deadline:
        started = time.monotonic()

        try:
            current = now_tehran()
            hour_key = current.strftime("%Y-%m-%d-%H")

            # FIFO hour marker. NewsStore is owned only by the processor.
            if hour_key != last_hour_key:
                frame_queue.put(("hour", current))
                last_hour_key = hour_key

            # IMPORTANT: this is now executed on the same thread that created
            # Playwright, eliminating the greenlet "different thread" error.
            png = browser.capture()
            frame = image_from_png(png)

            if frame is None:
                raise RuntimeError("Could not decode video screenshot.")

            mode, score = detector.detect(frame)

            if mode:
                capital = detector.scan_image(frame, mode)
                capital_changed = FrameChange.changed(
                    previous_capital,
                    capital,
                    threshold,
                )

                text_changed = False
                text_img = None

                if mode == "mode2":
                    text_img = detector.textnews_image(frame)
                    text_changed = FrameChange.changed(
                        previous_textnews,
                        text_img,
                        threshold,
                    )

                # Mode switch -> always process.
                # Same mode -> process only if the monitored news area changed.
                # In mode 2, a TextNews-only change also enters the FIFO.
                if mode != last_layout or capital_changed or text_changed:
                    frame_queue.put(
                        (
                            "frame",
                            frame,
                            (current, mode, score),
                        )
                    )

                    previous_capital = capital.copy()
                    previous_textnews = (
                        text_img.copy() if mode == "mode2" else None
                    )
                    last_layout = mode

            else:
                # Mode 3 / unknown scene: nothing is processed.
                previous_capital = None
                previous_textnews = None
                last_layout = None

        except Exception:
            logging.exception("Capture loop error")
            time.sleep(2)

        elapsed = time.monotonic() - started
        time.sleep(max(0, interval - elapsed))


def process_loop(detector, ocr, store, publisher, frame_queue, stop):
    """
    This thread performs only non-Playwright work:
    OpenCV, OCR, JSON storage and git publishing.
    """
    while not stop.is_set() or frame_queue.size() > 0:
        try:
            item = frame_queue.get(timeout=1)
        except queue.Empty:
            continue

        try:
            kind = item[0]

            if kind == "hour":
                current = item[1]
                store.current_bucket(current)
                store.save(current)
                publisher.publish(force=True)
                continue

            _, frame, captured = item
            captured_at, mode, score = captured

            # Re-check the queued frame itself. This prevents a stale frame
            # from being interpreted using the current screen state.
            detected_mode, _ = detector.detect(frame)

            if detected_mode != mode:
                mode = detected_mode

            if not mode:
                continue

            store.current_bucket(captured_at)

            capital = detector.scan_image(frame, mode)
            capital_text = ocr.extract(
                capital,
                ocr.psm_capital,
                red_text=True,
            )

            changed = False

            if capital_text and len(capital_text) >= 3:
                changed = (
                    store.add(
                        "CapitalNews",
                        capital_text,
                        captured_at,
                    )
                    or changed
                )

            if mode == "mode2":
                text_img = detector.textnews_image(frame)
                text = ocr.extract(
                    text_img,
                    ocr.psm_text,
                )

                if text and len(text) >= 5:
                    changed = (
                        store.add(
                            "TextNews",
                            text,
                            captured_at,
                        )
                        or changed
                    )

            if changed:
                store.save(captured_at)
                publisher.publish()

        except Exception:
            logging.exception("Processing loop error")

        finally:
            frame_queue.task_done()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(ROOT / "config.json"),
    )
    parser.add_argument(
        "--debug-once",
        action="store_true",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    config = load_config(args.config)
    browser = LiveBrowser(config)
    detector = LayoutDetector(config)
    ocr = OCR(config)
    store = NewsStore(ROOT / "api/news.json")
    publisher = GitPublisher(ROOT / "api/news.json")
    stop = threading.Event()

    try:
        # Browser and Playwright are created on the main thread.
        browser.start()

        if args.debug_once:
            debug = ROOT / "debug"
            debug.mkdir(exist_ok=True)

            data = browser.capture()
            (debug / "video-frame.png").write_bytes(data)
            (debug / "video-info.json").write_text(
                json.dumps(
                    browser.info(),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            logging.info("Debug frame saved.")
            return 0

        frame_queue = FrameQueue()

        # Only OCR/storage/publishing runs in a worker thread.
        # Playwright never crosses this thread boundary.
        processor = threading.Thread(
            target=process_loop,
            args=(
                detector,
                ocr,
                store,
                publisher,
                frame_queue,
                stop,
            ),
            daemon=True,
            name="processor",
        )
        processor.start()

        deadline = time.monotonic() + int(config["worker_minutes"]) * 60

        # Capture MUST remain on the main thread because Playwright sync API
        # is not thread-safe.
        capture_loop(
            browser,
            detector,
            frame_queue,
            stop,
            config,
            deadline,
        )

        stop.set()

        # Drain the FIFO. We intentionally do not throw queued frames away.
        processor.join(timeout=120)

        store.save()
        publisher.publish(force=True)
        return 0

    finally:
        stop.set()
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
