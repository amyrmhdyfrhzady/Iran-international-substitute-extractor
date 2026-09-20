import argparse
import json
import logging
import os
import queue
import subprocess
import sys
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

ROOT=Path(__file__).resolve().parents[1]
TEHRAN=ZoneInfo("Asia/Tehran")

def load_config(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def now_tehran():
    return datetime.now(TEHRAN)

def image_from_png(data):
    return cv2.imdecode(np.frombuffer(data,dtype=np.uint8),cv2.IMREAD_COLOR)

class GitPublisher:
    def __init__(self,path):
        self.path=Path(path)
        self.last=time.monotonic()-999
        self.interval=20

    def publish(self,force=False):
        if not force and time.monotonic()-self.last<self.interval:
            return
        self.last=time.monotonic()
        try:
            subprocess.run(["git","config","user.name","github-actions[bot]"],check=True)
            subprocess.run(["git","config","user.email","41898282+github-actions[bot]@users.noreply.github.com"],check=True)
            subprocess.run(["git","add",str(self.path)],check=True)
            changed=subprocess.run(["git","diff","--cached","--quiet"]).returncode != 0
            if not changed:
                return
            subprocess.run(["git","commit","-m","Update subtitle API"],check=True)
            # The workflow has one active worker at a time.
            result=subprocess.run(["git","push"],capture_output=True,text=True)
            if result.returncode!=0:
                logging.warning("git push failed: %s",result.stderr.strip())
        except Exception as exc:
            logging.warning("Publish failed: %s",exc)

def capture_loop(browser, detector, frame_queue, stop, config):
    previous_capital=None
    previous_textnews=None
    last_layout=None
    threshold=float(config["change_threshold"])
    interval=float(config["capture_interval_seconds"])
    while not stop.is_set():
        started=time.monotonic()
        try:
            frame=image_from_png(browser.capture())
            if frame is None:
                raise RuntimeError("Could not decode video screenshot.")

            mode,score=detector.detect(frame)

            if mode:
                capital=detector.scan_image(frame,mode)
                capital_changed=FrameChange.changed(previous_capital,capital,threshold)

                text_changed=False
                if mode=="mode2":
                    text_img=detector.textnews_image(frame)
                    text_changed=FrameChange.changed(previous_textnews,text_img,threshold)

                # CapitalNews is the primary gate. In mode 2, TextNews is
                # also watched so a text-only change is not lost.
                if mode!=last_layout or capital_changed or text_changed:
                    frame_queue.put(frame,(now_tehran(),mode,score))
                    previous_capital=capital.copy()
                    previous_textnews=text_img.copy() if mode=="mode2" else None
                    last_layout=mode
            else:
                # Do not process anything in mode 3 / unknown scenes.
                previous_capital=None
                previous_textnews=None
                last_layout=None

        except Exception:
            logging.exception("Capture loop error")
            time.sleep(2)

        elapsed=time.monotonic()-started
        time.sleep(max(0,interval-elapsed))

def process_loop(browser, detector, ocr, store, publisher, frame_queue, stop, config):
    while not stop.is_set() or frame_queue.size()>0:
        try:
            frame,captured=frame_queue.get(timeout=1)
        except queue.Empty:
            continue
        try:
            captured_at,mode,score=captured
            # Re-detect on the queued frame. This protects against a stale
            # capture being interpreted under the current layout.
            detected_mode,_=detector.detect(frame)
            if detected_mode!=mode:
                mode=detected_mode
            if not mode:
                continue

            capital=detector.scan_image(frame,mode)
            capital_text=ocr.extract(capital,ocr.psm_capital,red_text=True)

            if not capital_text or len(capital_text)<3:
                continue

            if store.add("CapitalNews",capital_text,captured_at):
                store.save()
                publisher.publish()

            if mode=="mode2":
                text_img=detector.textnews_image(frame)
                text=ocr.extract(text_img,ocr.psm_text)
                if text and len(text)>=5:
                    if store.add("TextNews",text,captured_at):
                        store.save()
                        publisher.publish()
        except Exception:
            logging.exception("Processing loop error")
        finally:
            frame_queue.task_done()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",default=str(ROOT/"config.json"))
    ap.add_argument("--debug-once",action="store_true")
    args=ap.parse_args()

    logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(message)s")
    config=load_config(args.config)
    browser=LiveBrowser(config)
    detector=LayoutDetector(config)
    ocr=OCR(config)
    store=NewsStore(ROOT/"api/news.json")
    publisher=GitPublisher(ROOT/"api/news.json")
    stop=threading.Event()

    try:
        browser.start()
        if args.debug_once:
            d=ROOT/"debug"; d.mkdir(exist_ok=True)
            data=browser.capture()
            (d/"video-frame.png").write_bytes(data)
            (d/"video-info.json").write_text(json.dumps(browser.info(),ensure_ascii=False,indent=2),encoding="utf-8")
            logging.info("Debug frame saved.")
            return 0

        fq=FrameQueue()
        capture=threading.Thread(
            target=capture_loop,
            args=(browser,detector,fq,stop,config),
            daemon=True,
            name="capture",
        )
        processor=threading.Thread(
            target=process_loop,
            args=(browser,detector,ocr,store,publisher,fq,stop,config),
            daemon=True,
            name="processor",
        )
        capture.start()
        processor.start()

        deadline=time.monotonic()+int(config["worker_minutes"])*60
        last_hour_key=None
        while time.monotonic()<deadline:
            current=now_tehran()
            hour_key=current.strftime("%Y-%m-%d-%H")
            if hour_key!=last_hour_key:
                store.current_bucket(current)
                store.save(current)
                publisher.publish(force=True)
                last_hour_key=hour_key
            time.sleep(5)

        stop.set()
        capture.join(timeout=10)
        # Let the FIFO drain. No queued frame is deliberately discarded.
        processor.join(timeout=120)
        store.save()
        publisher.publish(force=True)
        return 0
    finally:
        stop.set()
        browser.close()

if __name__=="__main__":
    raise SystemExit(main())
