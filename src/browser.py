import logging
import time
from playwright.sync_api import sync_playwright

class LiveBrowser:
    def __init__(self, config):
        self.config=config
        self.pw=None
        self.browser=None
        self.page=None

    def start(self):
        self.pw=sync_playwright().start()
        self.browser=self.pw.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
            ],
        )
        self.page=self.browser.new_page(viewport={"width":1920,"height":1080}, device_scale_factor=1)
        self.page.goto(self.config["url"], wait_until="domcontentloaded", timeout=120000)
        self._wait_for_video()

    def _wait_for_video(self):
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            videos=self.page.locator("video")
            if videos.count():
                for i in range(videos.count()):
                    v=videos.nth(i)
                    try:
                        if v.is_visible() and v.bounding_box():
                            logging.info("Live video found.")
                            return
                    except Exception:
                        pass
            time.sleep(2)
        raise RuntimeError("No visible video element found.")

    def capture(self):
        return self.page.locator("video").first.screenshot(type="png", animations="disabled")

    def info(self):
        return self.page.locator("video").first.evaluate("""v => ({
            clientWidth:v.clientWidth, clientHeight:v.clientHeight,
            videoWidth:v.videoWidth, videoHeight:v.videoHeight,
            paused:v.paused, readyState:v.readyState
        })""")

    def recover(self):
        logging.warning("Recovering live page...")
        try:
            self.page.reload(wait_until="domcontentloaded", timeout=120000)
            self._wait_for_video()
        except Exception:
            logging.exception("Recovery failed")

    def close(self):
        try:
            if self.browser: self.browser.close()
        finally:
            if self.pw: self.pw.stop()
