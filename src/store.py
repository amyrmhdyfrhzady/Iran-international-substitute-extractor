import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from rapidfuzz.fuzz import ratio

TEHRAN=ZoneInfo("Asia/Tehran")

class NewsStore:
    def __init__(self,path):
        self.path=Path(path)
        if self.path.exists():
            try:
                self.data=json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data={"updated_at":None,"timezone":"Asia/Tehran","hours":[]}
        else:
            self.data={"updated_at":None,"timezone":"Asia/Tehran","hours":[]}
        self.data.setdefault("timezone","Asia/Tehran")
        self.data.setdefault("hours",[])
        self.data.setdefault("updated_at",None)

    @staticmethod
    def _day(now):
        return now.strftime("%-d %B %Y")

    def current_bucket(self, now=None):
        now=now or datetime.now(TEHRAN)
        time_label=now.strftime("%H:00")
        day=self._day(now)
        for bucket in self.data["hours"]:
            if bucket.get("time")==time_label and bucket.get("day")==day:
                return bucket
        bucket={"time":time_label,"day":day,"CapitalNews":[],"TextNews":[]}
        self.data["hours"].insert(0,bucket)
        return bucket

    def add(self, kind, text, now=None):
        text=text.strip()
        if not text or len(text)<3:
            return False
        bucket=self.current_bucket(now)
        arr=bucket[kind]
        for old in arr:
            if ratio(old,text)>=94:
                return False
        # Newest news at the top of its hourly section.
        arr.insert(0,text)
        return True

    def save(self, now=None):
        self.data["updated_at"]=(now or datetime.now(TEHRAN)).isoformat()
        self.data["hours"].sort(
            key=lambda x: datetime.strptime(
                f'{x["day"]} {x["time"]}',
                "%d %B %Y %H:%M"
            ),
            reverse=True
        )
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text(
            json.dumps(self.data,ensure_ascii=False,indent=2),
            encoding="utf-8"
        )
