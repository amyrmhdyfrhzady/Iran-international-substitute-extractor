import re
import cv2
import numpy as np
import pytesseract
from rapidfuzz.fuzz import ratio

class OCR:
    def __init__(self, config):
        self.scale=int(config["ocr"]["scale"])
        self.lang=config["ocr"]["language"]
        self.psm_capital=int(config["ocr"]["psm_capital"])
        self.psm_text=int(config["ocr"]["psm_textnews"])

    def preprocess(self,img):
        gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        gray=cv2.resize(gray,None,fx=self.scale,fy=self.scale,interpolation=cv2.INTER_CUBIC)
        gray=cv2.GaussianBlur(gray,(3,3),0)
        # Keep dark/red text as dark foreground. Otsu is robust across changing backgrounds.
        _,bw=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        return bw

    def extract(self,img,psm,red_text=False):
        if img is None or img.size==0: return ""
        if red_text:
            bw=self.red_text_image(img)
        else:
            bw=self.preprocess(img)
        text=pytesseract.image_to_string(bw,lang=self.lang,config=f"--oem 1 --psm {psm}")
        return self.clean(text)

    def red_text_image(self,img):
        # CapitalNews uses red lettering on white. Isolate the red pixels so
        # presenter clothing, logos and the white background do not become OCR noise.
        hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV)
        m1=cv2.inRange(hsv,np.array([0,70,60]),np.array([15,255,255]))
        m2=cv2.inRange(hsv,np.array([165,70,60]),np.array([180,255,255]))
        red=m1|m2
        red=cv2.morphologyEx(red,cv2.MORPH_CLOSE,np.ones((2,2),np.uint8))
        out=np.where(red>0,0,255).astype(np.uint8)
        out=cv2.resize(out,None,fx=self.scale+1,fy=self.scale+1,interpolation=cv2.INTER_CUBIC)
        out=cv2.copyMakeBorder(out,20,20,20,20,cv2.BORDER_CONSTANT,value=255)
        return out

    @staticmethod
    def clean(text):
        text=text.replace("\u200c"," ")
        text=re.sub(r"[\r\n]+"," ",text)
        text=re.sub(r"\s+"," ",text).strip()
        for a,b in {"ي":"ی","ى":"ی","ك":"ک","ۀ":"هٔ","ة":"ه"}.items():
            text=text.replace(a,b)
        text=re.sub(r"\s+([،؛؟,.!])",r"\1",text)
        return text.strip(" -–—|")

    @staticmethod
    def similar(a,b):
        if not a or not b: return 0
        return ratio(a,b)/100
