import queue
import threading
import time
import cv2
import numpy as np

class FrameQueue:
    def __init__(self):
        self.q=queue.Queue()
        self.stop_event=threading.Event()

    def put(self, item):
        self.q.put(item)

    def get(self, timeout=1):
        return self.q.get(timeout=timeout)

    def task_done(self):
        self.q.task_done()

    def size(self):
        return self.q.qsize()

class FrameChange:
    @staticmethod
    def changed(previous,current,threshold=0.012):
        if previous is None:
            return True
        if previous.shape != current.shape:
            return True
        a=cv2.cvtColor(previous,cv2.COLOR_BGR2GRAY)
        b=cv2.cvtColor(current,cv2.COLOR_BGR2GRAY)
        diff=cv2.absdiff(a,b)
        # Downsample the comparison so OCR-like detail does not dominate.
        diff=cv2.resize(diff,(320,80),interpolation=cv2.INTER_AREA)
        return float(np.mean(diff>18))>=threshold
