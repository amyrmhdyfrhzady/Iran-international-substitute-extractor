import cv2
import numpy as np

class LayoutDetector:
    def __init__(self, config):
        self.config=config
        self.regions=config["regions"]
        self.red_min_saturation=config["layout_detection"]["red_min_saturation"]
        self.red_min_value=config["layout_detection"]["red_min_value"]
        self.white_min_value=config["layout_detection"]["white_min_value"]

    @staticmethod
    def crop(frame, region):
        h,w=frame.shape[:2]
        x=max(0,int(region["x"]*w)); y=max(0,int(region["y"]*h))
        x2=min(w,int((region["x"]+region["width"])*w))
        y2=min(h,int((region["y"]+region["height"])*h))
        if x2<=x or y2<=y: return None
        return frame[y:y2,x:x2]

    def _red_white_score(self, image):
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)

        red1=cv2.inRange(
            hsv,
            np.array([0,self.red_min_saturation,self.red_min_value]),
            np.array([12,255,255])
        )
        red2=cv2.inRange(
            hsv,
            np.array([170,self.red_min_saturation,self.red_min_value]),
            np.array([180,255,255])
        )
        red=(red1|red2)>0

        # CapitalNews is red writing on a white panel. The test below checks
        # the local neighborhood around red pixels, so a red studio jacket
        # or a small red/blue channel logo does not qualify.
        white=((hsv[:,:,2]>=self.white_min_value)&(hsv[:,:,1]<70)).astype(np.uint8)
        local_white=cv2.blur(white.astype(np.float32),(15,15))
        valid=red & (local_white>=0.55)

        n=int(valid.sum())
        if n<30:
            return 0.0

        ys,xs=np.where(valid)
        spread=(np.percentile(xs,90)-np.percentile(xs,10))/max(1,image.shape[1])

        bins=np.histogram(xs,bins=12,range=(0,image.shape[1]))[0]
        occupied=float(np.count_nonzero(bins>2))/12.0

        # Normalized score. Text should occupy a distributed horizontal band.
        density=n/max(1,image.shape[0]*image.shape[1])
        return float(min(1.0,density*100 + spread*0.5 + occupied*0.5))

    def detect(self, frame):
        m1=self._red_white_score(self.crop(frame,self.regions["mode1"]["capital"]))
        m2=self._red_white_score(self.crop(frame,self.regions["mode2"]["capital"]))

        # Mode 2 is checked first because its capital region is higher.
        # A high score is required; the detector intentionally rejects
        # white/black text and scenes where the red pixels are concentrated
        # in a small channel/logo.
        if m2>=0.16 and m2>=m1*0.75:
            return "mode2", m2
        if m1>=0.16:
            return "mode1", m1
        return None, max(m1,m2)

    def scan_image(self, frame, mode):
        r=self.regions[mode]["capital"]
        return self.crop(frame,r)

    def textnews_image(self, frame):
        return self.crop(frame,self.regions["mode2"]["textnews"])
