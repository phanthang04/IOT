#!/usr/bin/env python3
"""
Smart Door Lock - Python Backend Server
Face Recognition + Palm Verification + Telegram Bot
"""

import os
import sys
import io
import json
import uuid
import shutil
import logging
import threading
import asyncio
import time
from datetime import datetime
from flask import Response
from pathlib import Path
import database as db

# Fix Windows console encoding for emoji/Vietnamese
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import cv2
import numpy as np
import face_recognition
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions
from flask import Flask, request, jsonify, send_from_directory
import requests
import telegram

# ─── ĐƯỜNG DẪN ────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent

# FIX LỖI Ổ C BỊ ĐẦY (0 GB Free)
TMP_DIR = BASE_DIR / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
import os, tempfile
os.environ["TMP"] = str(TMP_DIR)
os.environ["TEMP"] = str(TMP_DIR)
os.environ["TMPDIR"] = str(TMP_DIR)
tempfile.tempdir = str(TMP_DIR)

DATA_DIR      = BASE_DIR / "data"
STRANGERS_DIR = DATA_DIR / "strangers"
LOG_DIR       = DATA_DIR / "logs"
USERS_DIR     = DATA_DIR / "users"  # Thư mục user (dùng cho route xem ảnh)

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5000

for d in [STRANGERS_DIR, LOG_DIR, USERS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── CONFIG PERSISTENCE ──────────────────────────────────────
DEFAULT_CONFIG = {
    "telegram_token":   "8695084118:AAHRJEiboIMhx37kM0CRXxaGtSSshnowf4A",
    "telegram_chat_id": "5247029660",
    "door_time": "10",
    "esp32_ip": "",
    "esp32_stream_url": ""
}

def load_config():
    cfg = {}
    for k, v in DEFAULT_CONFIG.items():
        cfg[k] = db.get_config_val(k, v)
    return cfg

def save_config_to_file(config):
    for k, v in config.items():
        db.set_config_val(k, v)

app_config = load_config()
esp32_ip = app_config.get("esp32_ip", "")
esp32_stream_url = app_config.get("esp32_stream_url", "")

# ─── LOGGING ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ─── CORS ────────────────────────────────────────────────────
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response

@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def handle_options(path):
    return "", 204

# ─── DATABASE ─────────────────────────────────────────────────
def load_users():
    return db.load_users_db()

def save_users(users):
    # Dùng cho các hàm insert (nay đã tự động ghi vao db)
    pass

def get_user(user_id):
    return load_users().get(user_id)

# ─── QUẢN LÝ DỮ LIỆU CŨ ──────────────────────────────────────
def migrate_legacy_files():
    pass

# ─── FACE RECOGNITION ENGINE ─────────────────────────────────
class FaceEngine:
    def __init__(self):
        self.known_encodings = []
        self.known_user_ids  = []
        self.load_all_faces()

    def load_all_faces(self):
        self.known_encodings = []
        self.known_user_ids  = []
        users = load_users()
        for user_id in users.keys():
            images = db.get_all_user_images(user_id, "face")
            for img_info in images:
                try:
                    img_bytes = img_info['bytes']
                    np_arr = np.frombuffer(img_bytes, np.uint8)
                    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    if img is not None:
                        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        encs = face_recognition.face_encodings(img_rgb)
                        if encs:
                            self.known_encodings.append(encs[0])
                            self.known_user_ids.append(user_id)
                except Exception as e:
                    log.error(f"Error loading face from DB for {user_id}: {e}")
        log.info(f"Tong so encoding khuon mat: {len(self.known_encodings)}")

    def recognize(self, image_bytes) -> dict:
        try:
            np_arr  = np.frombuffer(image_bytes, np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                return {"status": "error", "message": "Invalid image"}
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

            # Tối ưu: Resize ảnh nhỏ lại (ví dụ chiều ngang max 640) để xử lý nhận diện nhanh hơn
            h, w = img_rgb.shape[:2]
            if w > 640:
                scale = 640.0 / w
                img_rgb = cv2.resize(img_rgb, (640, int(h * scale)))


            locations = face_recognition.face_locations(img_rgb)
            encodings = face_recognition.face_encodings(img_rgb, locations)

            if not encodings:
                return {"status": "no_face"}
            if not self.known_encodings:
                return {"status": "stranger"}

            test_enc  = encodings[0]
            distances = face_recognition.face_distance(self.known_encodings, test_enc)
            best_idx  = int(np.argmin(distances))
            best_dist = float(distances[best_idx])

            THRESHOLD = 0.45
            if best_dist < THRESHOLD:
                user_id = self.known_user_ids[best_idx]
                user    = get_user(user_id)
                return {
                    "status":     "recognized",
                    "user_id":    user_id,
                    "name":       user["name"] if user else user_id,
                    "confidence": round((1 - best_dist) * 100, 1)
                }
            else:
                return {"status": "stranger"}
        except Exception as e:
            log.error(f"Face recognition error: {e}")
            return {"status": "error", "message": str(e)}

    def register_face(self, user_id, image_bytes, index):
        try:
            np_arr  = np.frombuffer(image_bytes, np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                return False
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            encs = face_recognition.face_encodings(img_rgb)
            if not encs:
                return False
            
            # Lưu ảnh mã hóa vào SQLite
            db.save_encrypted_image(user_id, "face", index, image_bytes)
            return True
        except Exception as e:
            log.error(f"Register face error: {e}")
            return False

# ─── PALM RECOGNITION ENGINE (Mediapipe + ORB) ──────────────
class PalmEngine:
    def __init__(self):
        # Dùng mediapipe.tasks API (tương thích Python 3.14)
        model_path = str(BASE_DIR / "data" / "hand_landmarker.task")
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            num_hands=1,
            min_hand_detection_confidence=0.5
        )
        self.hand_detector = HandLandmarker.create_from_options(options)
        
        # Chuyển sang SIFT cho độ chính xác cao hơn ORB
        self.sift = cv2.SIFT_create()
        self.bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
        self.known_descriptors = {}  # user_id -> list of descriptors
        self.load_all_palms()

    def _extract_palm_roi(self, img_rgb):
        """Dùng Mediapipe HandLandmarker tìm bàn tay và crop vùng lòng bàn tay."""
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
        results = self.hand_detector.detect(mp_image)
        if not results.hand_landmarks or len(results.hand_landmarks) == 0:
            return None
        hand = results.hand_landmarks[0]
        h, w = img_rgb.shape[:2]
        xs = [lm.x * w for lm in hand]
        ys = [lm.y * h for lm in hand]
        x1 = max(0, int(min(xs)) - 20)
        y1 = max(0, int(min(ys)) - 20)
        x2 = min(w, int(max(xs)) + 20)
        y2 = min(h, int(max(ys)) + 20)
        if x2 - x1 < 30 or y2 - y1 < 30:
            return None
        roi = img_rgb[y1:y2, x1:x2]
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        
        # Cân bằng ánh sáng (Histogram Equalization) để chống nhiễu sáng
        roi_gray = cv2.equalizeHist(roi_gray)
        roi_gray = cv2.resize(roi_gray, (200, 200))
        return roi_gray

    def _compute_descriptor(self, roi_gray):
        """Trích xuất SIFT descriptors từ ảnh ROI."""
        kp, des = self.sift.detectAndCompute(roi_gray, None)
        return des

    def load_all_palms(self):
        self.known_descriptors = {}
        users = load_users()
        for user_id in users.keys():
            images = db.get_all_user_images(user_id, "palm")
            descs = []
            for img_info in images:
                try:
                    img_bytes = img_info['bytes']
                    np_arr = np.frombuffer(img_bytes, np.uint8)
                    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    if img is None:
                        continue
                    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    roi = self._extract_palm_roi(img_rgb)
                    if roi is not None:
                        des = self._compute_descriptor(roi)
                        if des is not None:
                            descs.append(des)
                except Exception as e:
                    log.error(f"Error loading palm for {user_id}: {e}")
            if descs:
                self.known_descriptors[user_id] = descs
        log.info(f"Palm descriptors loaded for {len(self.known_descriptors)} users")

    def verify(self, image_bytes, user_id) -> dict:
        """Xác thực lòng bàn tay của user_id cụ thể."""
        try:
            np_arr = np.frombuffer(image_bytes, np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                return {"status": "error", "message": "Invalid image"}
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

            roi = self._extract_palm_roi(img_rgb)
            if roi is None:
                return {"status": "no_palm"}

            test_des = self._compute_descriptor(roi)
            if test_des is None:
                return {"status": "no_palm"}

            if user_id not in self.known_descriptors:
                return {"status": "no_data", "message": "User chua dang ky long ban tay"}

            best_score = 0
            for ref_des in self.known_descriptors[user_id]:
                try:
                    matches = self.bf.knnMatch(test_des, ref_des, k=2)
                    good = []
                    for m_n in matches:
                        if len(m_n) == 2:
                            m, n = m_n
                            # Ratio test tiêu chuẩn của SIFT (Lowe's ratio test = 0.7)
                            if m.distance < 0.7 * n.distance:
                                good.append(m)
                    
                    # Tính % match. SIFT thường tìm được hàng trăm keypoints, 
                    # Nếu có > 15 good matches thì tay đã rất giống.
                    # Tính theo tỷ lệ tương đối: 15 good matches = 100% confidence.
                    score = min((len(good) / 15.0) * 100, 100.0)
                    best_score = max(best_score, 100.0)
                except Exception:
                    continue

            PALM_THRESHOLD = 00.0  # Ngưỡng tối thiểu để coi là có tín hiệu lòng bàn tay hợp lệ
            
            if best_score >= PALM_THRESHOLD:
                return {
                    "status": "matched",
                    "confidence": round(best_score, 1)
                }
            else:
                return {
                    "status": "not_matched",
                    "confidence": round(best_score, 1)
                }
        except Exception as e:
            log.error(f"Palm verify error: {e}")
            return {"status": "error", "message": str(e)}

    def register_palm(self, user_id, image_bytes, index):
        try:
            np_arr = np.frombuffer(image_bytes, np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                return False
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            roi = self._extract_palm_roi(img_rgb)
            if roi is None:
                return False
            des = self._compute_descriptor(roi)
            if des is None:
                return False
            db.save_encrypted_image(user_id, "palm", index, image_bytes)
            return True
        except Exception as e:
            log.error(f"Register palm error: {e}")
            return False

    def __init__(self):
        # Dùng mediapipe.tasks API (tương thích Python 3.14)
        model_path = str(BASE_DIR / "data" / "hand_landmarker.task")
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            num_hands=1,
            min_hand_detection_confidence=0.5
        )
        self.hand_detector = HandLandmarker.create_from_options(options)
        
        # Chuyển sang SIFT cho độ chính xác cao hơn ORB
        self.sift = cv2.SIFT_create()
        self.bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
        self.known_descriptors = {}  # user_id -> list of descriptors
        self.load_all_palms()

    def _extract_palm_roi(self, img_rgb):
        """Dùng Mediapipe HandLandmarker tìm bàn tay và crop vùng lòng bàn tay."""
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
        results = self.hand_detector.detect(mp_image)
        if not results.hand_landmarks or len(results.hand_landmarks) == 0:
            return None
        hand = results.hand_landmarks[0]
        h, w = img_rgb.shape[:2]
        xs = [lm.x * w for lm in hand]
        ys = [lm.y * h for lm in hand]
        x1 = max(0, int(min(xs)) - 20)
        y1 = max(0, int(min(ys)) - 20)
        x2 = min(w, int(max(xs)) + 20)
        y2 = min(h, int(max(ys)) + 20)
        if x2 - x1 < 30 or y2 - y1 < 30:
            return None
        roi = img_rgb[y1:y2, x1:x2]
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        
        # Cân bằng ánh sáng (Histogram Equalization) để chống nhiễu sáng
        roi_gray = cv2.equalizeHist(roi_gray)
        roi_gray = cv2.resize(roi_gray, (200, 200))
        return roi_gray

    def _compute_descriptor(self, roi_gray):
        """Trích xuất SIFT descriptors từ ảnh ROI."""
        kp, des = self.sift.detectAndCompute(roi_gray, None)
        return des

    def load_all_palms(self):
        self.known_descriptors = {}
        users = load_users()
        for user_id in users.keys():
            images = db.get_all_user_images(user_id, "palm")
            descs = []
            for img_info in images:
                try:
                    img_bytes = img_info['bytes']
                    np_arr = np.frombuffer(img_bytes, np.uint8)
                    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    if img is None:
                        continue
                    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    roi = self._extract_palm_roi(img_rgb)
                    if roi is not None:
                        des = self._compute_descriptor(roi)
                        if des is not None:
                            descs.append(des)
                except Exception as e:
                    log.error(f"Error loading palm for {user_id}: {e}")
            if descs:
                self.known_descriptors[user_id] = descs
        log.info(f"Palm descriptors loaded for {len(self.known_descriptors)} users")

    def verify(self, image_bytes, user_id) -> dict:
        """Xác thực lòng bàn tay của user_id cụ thể."""
        try:
            np_arr = np.frombuffer(image_bytes, np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                return {"status": "error", "message": "Invalid image"}
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

            roi = self._extract_palm_roi(img_rgb)
            if roi is None:
                return {"status": "no_palm"}

            test_des = self._compute_descriptor(roi)
            if test_des is None:
                return {"status": "no_palm"}

            if user_id not in self.known_descriptors:
                return {"status": "no_data", "message": "User chua dang ky long ban tay"}

            best_score = 0
            for ref_des in self.known_descriptors[user_id]:
                try:
                    matches = self.bf.knnMatch(test_des, ref_des, k=2)
                    good = []
                    for m_n in matches:
                        if len(m_n) == 2:
                            m, n = m_n
                            # Ratio test tiêu chuẩn của SIFT (Lowe's ratio test = 0.7)
                            if m.distance < 0.7 * n.distance:
                                good.append(m)
                    
                    # Tính điểm thực tế, KHÔNG ép 100%.
                    # Công thức cũ sai ở 2 điểm:
                    #   1) best_score = max(best_score, 100.0) -> luôn 100%
                    #   2) PALM_THRESHOLD = 0.0 -> điểm nào cũng matched
                    good_count = len(good)
                    ref_count = len(ref_des) if ref_des is not None else 0
                    test_count = len(test_des) if test_des is not None else 0
                    base_count = max(1, min(ref_count, test_count))

                    match_ratio = good_count / base_count

                    # 80 good matches mới được xem là rất tốt.
                    # match_ratio 0.30 tương đương mức rất giống.
                    score_by_count = min((good_count / 80.0) * 100.0, 100.0)
                    score_by_ratio = min((match_ratio / 0.30) * 100.0, 100.0)

                    score = (score_by_count * 0.7) + (score_by_ratio * 0.3)
                    best_score = max(best_score, score)
                except Exception:
                    continue

            # Ngưỡng palm chỉ để xác định tay có khớp tương đối hay không.
            # Mở cửa vẫn dựa vào trung bình Face + Palm >= 70 trong process_auth_sequence().
            PALM_THRESHOLD = 45.0
            
            if best_score >= PALM_THRESHOLD:
                return {
                    "status": "matched",
                    "confidence": round(best_score, 1)
                }
            else:
                return {
                    "status": "not_matched",
                    "confidence": round(best_score, 1)
                }
        except Exception as e:
            log.error(f"Palm verify error: {e}")
            return {"status": "error", "message": str(e)}

    def register_palm(self, user_id, image_bytes, index):
        try:
            np_arr = np.frombuffer(image_bytes, np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                return False
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            roi = self._extract_palm_roi(img_rgb)
            if roi is None:
                return False
            des = self._compute_descriptor(roi)
            if des is None:
                return False
            db.save_encrypted_image(user_id, "palm", index, image_bytes)
            return True
        except Exception as e:
            log.error(f"Register palm error: {e}")
            return False

# ─── TELEGRAM BOT (dedicated event loop) ─────────────────────
class TelegramNotifier:
    def __init__(self):
        self._loop   = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._bot = None
        self._update_bot()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _update_bot(self):
        token = app_config.get("telegram_token", "")
        if token:
            try:
                self._bot = telegram.Bot(token=token)
            except Exception as e:
                log.error(f"Telegram bot init error: {e}")
                self._bot = None
        else:
            self._bot = None

    def reload(self):
        self._update_bot()

    def _chat_id(self):
        return app_config.get("telegram_chat_id", "")

    def send(self, text):
        if not self._bot or not self._chat_id():
            log.warning("Telegram not configured, skipping send")
            return
        future = asyncio.run_coroutine_threadsafe(self._send_text(text), self._loop)
        try:
            future.result(timeout=15)
        except Exception as e:
            log.error(f"Telegram send error: {e}")

    def send_photo(self, image_bytes, caption=""):
        if not self._bot or not self._chat_id():
            return
        future = asyncio.run_coroutine_threadsafe(self._send_photo(image_bytes, caption), self._loop)
        try:
            future.result(timeout=15)
        except Exception as e:
            log.error(f"Telegram photo error: {e}")

    async def _send_text(self, text):
        await self._bot.send_message(chat_id=self._chat_id(), text=text)

    async def _send_photo(self, image_bytes, caption):
        await self._bot.send_photo(chat_id=self._chat_id(), photo=image_bytes, caption=caption)

    def notify_access(self, name, user_id, method, confidence=None):
        """Gửi thông báo mở cửa chi tiết"""
        now_time = datetime.now().strftime("%H:%M:%S")
        now_date = datetime.now().strftime("%d/%m/%Y")
        methods = {
            "face+palm": "Khuôn mặt + Lòng bàn tay",
            "face": "Nhận dạng khuôn mặt",
            "palm": "Nhận dạng lòng bàn tay",
            "manual_web": "Mở thủ công từ Web",
            "test_face": "Test khuôn mặt (Camera Web)",
            "test_palm": "Test lòng bàn tay (Camera Web)",
            "dual_verify": "Xác thực kép (Mặt + Tay)",
        }
        method_text = methods.get(method, method)
        conf_text = f"\n📊 Độ tin cậy: {confidence}%" if confidence else ""
        self.send(
            f"🔓 CỬA ĐÃ MỞ\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 Người mở: {name}\n"
            f"🔑 Phương thức: {method_text}{conf_text}\n"
            f"📅 Ngày: {now_date}\n"
            f"🕐 Giờ: {now_time}\n"
            f"━━━━━━━━━━━━━━━━"
        )

    def notify_stranger(self, image_bytes):
        now_time = datetime.now().strftime("%H:%M:%S")
        now_date = datetime.now().strftime("%d/%m/%Y")
        self.send_photo(
            image_bytes,
            caption=(
                f"🚨 CẢNH BÁO: NGƯỜI LẠ!\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Có người không rõ danh tính!\n"
                f"📅 Ngày: {now_date}\n"
                f"🕐 Giờ: {now_time}\n"
                f"━━━━━━━━━━━━━━━━"
            )
        )

    def notify_palm_fail(self, name, face_conf=None, palm_conf=None, avg_conf=None, reason=None):
        now_time = datetime.now().strftime("%H:%M:%S")
        now_date = datetime.now().strftime("%d/%m/%Y")
        
        conf_parts = []
        if face_conf is not None:
            conf_parts.append(f"Face: {face_conf}%")
        if palm_conf is not None:
            conf_parts.append(f"Palm: {palm_conf}%")
        if avg_conf is not None:
            conf_parts.append(f"Trung bình: {avg_conf}%")
            
        conf_text = f"\n📊 Độ tin cậy: " + ", ".join(conf_parts) if conf_parts else ""
        reason_text = f"\n🔴 Lý do: {reason}" if reason else "\n🔴 Lý do: Lòng bàn tay không khớp"
        
        self.send(
            f"⚠️ XÁC THỰC THẤT BẠI\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 Người xác thực: {name}\n"
            f"🔑 Phương thức: Khuôn mặt + Lòng bàn tay{reason_text}{conf_text}\n"
            f"📅 Ngày: {now_date}\n"
            f"🕐 Giờ: {now_time}\n"
            f"━━━━━━━━━━━━━━━━"
        )

# ─── KHỞI TẠO ────────────────────────────────────────────────
face_engine = FaceEngine()
palm_engine = PalmEngine()
notifier    = TelegramNotifier()
auto_detect_enabled = True  # CỜ BẬT/TẮT TỰ ĐỘNG NHẬN DIỆN (SERVER-SIDE)

# ─── STREAMING CAMERA ─────────────────────────────────────────
# esp32_ip và esp32_stream_url đã được load từ config ở đầu file

def _update_esp32_ip_from_request():
    """Tự động cập nhật ESP32 IP từ request đến (nếu không phải localhost)."""
    global esp32_ip
    remote = request.remote_addr
    if remote and remote != "127.0.0.1" and remote != esp32_ip:
        esp32_ip = remote
        app_config["esp32_ip"] = esp32_ip
        save_config_to_file(app_config)
        log.info(f"Auto-detected ESP32 IP from request: {esp32_ip}")

@app.route("/api/esp32/register", methods=["POST"])
def register_esp32():
    global esp32_stream_url, esp32_ip
    data = request.json
    esp32_stream_url = data.get("stream_url")
    esp32_ip = data.get("ip") or request.remote_addr
    
    app_config["esp32_ip"] = esp32_ip
    app_config["esp32_stream_url"] = esp32_stream_url
    save_config_to_file(app_config)
    
    log.info(f"Registered ESP32: IP={esp32_ip}, stream={esp32_stream_url}")
    return jsonify({"status": "ok", "stream_url": esp32_stream_url})

@app.route("/api/esp32/status", methods=["GET"])
def esp32_status():
    """Trả về trạng thái kết nối và URL stream của ESP32."""
    return jsonify({
        "connected": bool(esp32_stream_url and esp32_ip),
        "stream_url": esp32_stream_url or None,
        "ip": esp32_ip or None
    })

def _proxy_esp32_stream():
    """Proxy MJPEG stream từ ESP32 về browser (low-latency)."""
    try:
        with requests.get(esp32_stream_url, stream=True, timeout=10) as r:
            for chunk in r.iter_content(chunk_size=4096):
                if chunk:
                    yield chunk
    except GeneratorExit:
        pass
    except Exception as e:
        log.warning(f"ESP32 stream proxy error: {e}")

@app.route("/api/stream", methods=["GET"])
def video_stream():
    """Stream MJPEG. Proxy trực tiếp từ ESP32 nếu đã kết nối."""
    if esp32_stream_url:
        try:
            return Response(_proxy_esp32_stream(), mimetype="multipart/x-mixed-replace;boundary=123456789000000000000987654321")
        except Exception as e:
            log.warning(f"ESP32 stream setup error: {e}")
    # Fallback: trả về ảnh báo chờ nếu ESP32 chưa kết nối
    def placeholder():
        msg = b'ESP32 chua ket noi. Vui long kiem tra ESP32.'
        frame = (
            b'--frame\r\n'
            b'Content-Type: text/plain\r\n\r\n' + msg + b'\r\n'
        )
        while True:
            try:
                yield frame
                time.sleep(2)
            except GeneratorExit:
                break
    return Response(placeholder(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/capture/esp32", methods=["GET"])
def capture_esp32():
    """Lấy 1 ảnh tĩnh (JPEG) trực tiếp từ ESP32 để đăng ký."""
    if not esp32_ip:
        return jsonify({"error": "ESP32 chưa kết nối"}), 400
    try:
        url = f"http://{esp32_ip}:82/capture"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return Response(resp.content, mimetype="image/jpeg")
        else:
            return jsonify({"error": f"ESP32 trả về lỗi: {resp.status_code}"}), 500
    except Exception as e:
        log.error(f"Error capturing from ESP32: {e}")
        return jsonify({"error": "Không thể kết nối đến ESP32"}), 500

def fetch_esp32_image():
    if not esp32_ip: return None
    try:
        resp = requests.get(f"http://{esp32_ip}:82/capture", timeout=5)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        log.error(f"Error fetching from ESP32: {e}")
    return None

def process_auth_sequence():
    log.info("Started auth sequence driven by SERVER")
    _push_event("motion")
    time.sleep(0.2)

    face_img = fetch_esp32_image()
    if not face_img:
        log.error("Failed to fetch image from ESP32 for face")
        return

    face_result = face_engine.recognize(face_img)
    if face_result.get("status") == "recognized":
        name = face_result.get("name")
        user_id = face_result.get("user_id")
        face_conf = float(face_result.get("confidence") or 0)

        _push_event("face_ok", {"name": name, "confidence": face_conf})

        VERIFY_THRESHOLD = 70.0
        PALM_SCAN_SECONDS = 7.0
        SCAN_INTERVAL = 0.2

        best_palm_conf = 0.0
        best_avg_conf = round(face_conf / 2.0, 1)
        deadline = time.time() + PALM_SCAN_SECONDS

        while time.time() < deadline:
            palm_img = fetch_esp32_image()
            if not palm_img:
                time.sleep(SCAN_INTERVAL)
                continue

            palm_result = palm_engine.verify(palm_img, user_id)
            palm_conf = float(palm_result.get("confidence") or 0)
            avg_conf = round((face_conf + palm_conf) / 2.0, 1)

            best_palm_conf = max(best_palm_conf, palm_conf)
            best_avg_conf = max(best_avg_conf, avg_conf)

            log.info(
                f"Dual verify: face={face_conf}%, palm={palm_conf}%, "
                f"avg={avg_conf}%, palm_status={palm_result.get('status')}"
            )

            if palm_result.get("status") == "matched" and avg_conf >= VERIFY_THRESHOLD:
                _push_event("palm_ok", {
                    "name": name,
                    "face_confidence": face_conf,
                    "palm_confidence": palm_conf,
                    "avg_confidence": avg_conf
                })
                notifier.notify_access(name, user_id, "face+palm", avg_conf)

                if esp32_ip:
                    for port in [82, 80]:
                        try:
                            requests.get(f"http://{esp32_ip}:{port}/open", timeout=3)
                            break
                        except Exception:
                            pass
                return

            time.sleep(SCAN_INTERVAL)

        _push_event("palm_fail", {
            "name": name,
            "face_confidence": face_conf,
            "palm_confidence": round(best_palm_conf, 1),
            "avg_confidence": round(best_avg_conf, 1)
        })
        notifier.notify_palm_fail(
            name,
            face_conf,
            round(best_palm_conf, 1),
            round(best_avg_conf, 1),
            "Quét lòng bàn tay 7 giây nhưng trung bình Face + Palm vẫn chưa đạt 70%"
        )

    elif face_result.get("status") == "no_face":
        _push_event("no_face")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = STRANGERS_DIR / f"stranger_{timestamp}.jpg"
        with open(save_path, "wb") as f:
            f.write(face_img)
        log.warning(f"Nguoi la detected! Saved: {save_path}")
        _push_event("face_fail")
        notifier.notify_stranger(face_img)

_is_processing_sequence = False

@app.route("/api/trigger_motion", methods=["GET"])
def trigger_motion():
    global _is_processing_sequence
    _update_esp32_ip_from_request()
    
    if not auto_detect_enabled:
        return jsonify({"status": "ignored", "reason": "auto_detect_off"})
        
    if _is_processing_sequence:
        return jsonify({"status": "ignored", "reason": "already_processing"})
        
    def sequence_wrapper():
        global _is_processing_sequence
        _is_processing_sequence = True
        try:
            process_auth_sequence()
        except Exception as e:
            log.error(f"Error in process_auth_sequence: {e}")
        finally:
            _is_processing_sequence = False
            
    threading.Thread(target=sequence_wrapper).start()
    return jsonify({"status": "processing"})

# Giữ endpoint /api/frame cho tương thích ngược (nếu vẫn muốn push frame thủ công)
@app.route("/api/frame", methods=["POST"])
def receive_frame():
    return jsonify({"status": "ok"})

# ═══════════════════════════════════════════════════════════════
#                         API ENDPOINTS
# ═══════════════════════════════════════════════════════════════

# ─── ESP32-CAM APIs ───────────────────────────────────────────
@app.route("/api/recognize/face", methods=["POST"])
def recognize_face():
    # Tự động lấy IP ESP32 từ request
    _update_esp32_ip_from_request()
    
    # Nếu tự động nhận diện bị TẮT từ Web, trả về no_face để ESP32 bỏ qua
    if not auto_detect_enabled:
        log.info("Auto-detect DISABLED, skipping face recognition")
        return jsonify({"status": "no_face"})
    
    image_bytes = request.data
    if not image_bytes:
        return jsonify({"status": "error", "message": "No image"}), 400
    result = face_engine.recognize(image_bytes)
    log.info(f"Face recognition: {result}")
    return jsonify(result)

@app.route("/api/recognize/palm", methods=["POST"])
def recognize_palm():
    """Xác thực lòng bàn tay cho user_id cụ thể (sau khi face OK)."""
    user_id = request.args.get("user_id", "")
    is_final = request.args.get("is_final", "false").lower() == "true"
    
    if not user_id:
        return jsonify({"status": "error", "message": "Missing user_id"}), 400
    image_bytes = request.data
    if not image_bytes:
        return jsonify({"status": "error", "message": "No image"}), 400
        
    result = palm_engine.verify(image_bytes, user_id)
    log.info(f"Palm verification for {user_id}: {result}")
    result.get("status") == "matched"
    # if result.get("status") == "matched":
    #     user = get_user(user_id)
    #     name = user["name"] if user else user_id
    #     threading.Thread(
    #         target=notifier.notify_access,
    #         args=(name, user_id, "face+palm", result.get("confidence"))
    #     ).start()
    # elif result.get("status") == "not_matched" and is_final:
    #     user = get_user(user_id)
    #     name = user["name"] if user else user_id
    #     palm_conf = result.get("confidence", 0)
    #     # Gửi Telegram chi tiết khi palm fail từ ESP32
    #     threading.Thread(
    #         target=notifier.notify_palm_fail,
    #         args=(name, None, palm_conf, None, "Lòng bàn tay không khớp")
    #     ).start()
    return jsonify(result)

@app.route("/api/alert/stranger", methods=["POST"])
def alert_stranger():
    image_bytes = request.data
    if not image_bytes:
        return jsonify({"status": "error"}), 400
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = STRANGERS_DIR / f"stranger_{timestamp}.jpg"
    with open(save_path, "wb") as f:
        f.write(image_bytes)
    log.warning(f"Nguoi la detected! Saved: {save_path}")
    threading.Thread(target=notifier.notify_stranger, args=(image_bytes,)).start()
    return jsonify({"status": "alert_sent"})

@app.route("/api/alert/palm_fail", methods=["POST"])
def alert_palm_fail():
    data = request.json or {}
    name = data.get("name", "Unknown")
    threading.Thread(target=notifier.notify_palm_fail, args=(name,)).start()
    return jsonify({"status": "ok"})

# ─── USER MANAGEMENT ─────────────────────────────────────────
@app.route("/api/users", methods=["GET"])
def list_users():
    users  = load_users()
    result = []
    for uid, info in users.items():
        face_count = db.count_user_images(uid, "face")
        palm_count = db.count_user_images(uid, "palm")
        result.append({
            "id":         uid,
            "name":       info.get("name", ""),
            "phone":      info.get("phone", ""),
            "role":       info.get("role", "user"),
            "has_face":   face_count > 0,
            "face_count": face_count,
            "has_palm":   palm_count > 0,
            "palm_count": palm_count,
            "created":    info.get("created", "")
        })
    return jsonify(result)

@app.route("/api/users", methods=["POST"])
def create_user():
    data = request.json
    if not data or "name" not in data:
        return jsonify({"error": "Thiếu tên người dùng"}), 400
    user_id = str(uuid.uuid4())[:8]
    data["created"] = datetime.now().isoformat()
    db.save_user_db(user_id, data)
    log.info(f"Created user: {data['name']} ({user_id})")
    return jsonify({"user_id": user_id, "message": "Tạo thành công"})

@app.route("/api/users/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    users = load_users()
    if user_id not in users:
        return jsonify({"error": "Không tìm thấy"}), 404
    name = users[user_id]["name"]
    # Xoá user và ảnh trong DB
    db.delete_user_db(user_id)
    face_engine.load_all_faces()
    palm_engine.load_all_palms()
    log.info(f"Deleted user: {name} ({user_id})")
    return jsonify({"message": f"Đã xóa {name}"})

@app.route("/api/users/<user_id>/face", methods=["POST"])
def register_face(user_id):
    if not get_user(user_id):
        return jsonify({"error": "User không tồn tại"}), 404
    index = request.args.get("index", 1, type=int)
    if index < 1 or index > 5:
        return jsonify({"error": "Index phải từ 1 đến 5"}), 400
    image_bytes = request.data
    if not image_bytes:
        return jsonify({"error": "Không có ảnh"}), 400
    success = face_engine.register_face(user_id, image_bytes, index)
    if success:
        return jsonify({"message": f"Đăng ký khuôn mặt {index}/5 thành công"})
    else:
        return jsonify({"error": "Không tìm thấy khuôn mặt trong ảnh"}), 400

@app.route("/api/users/<user_id>/face/done", methods=["POST"])
def face_done(user_id):
    face_engine.load_all_faces()
    return jsonify({"message": "Reload thành công"})

@app.route("/api/users/<user_id>/palm", methods=["POST"])
def register_palm(user_id):
    if not get_user(user_id):
        return jsonify({"error": "User không tồn tại"}), 404
    index = request.args.get("index", 1, type=int)
    if index < 1 or index > 5:
        return jsonify({"error": "Index phải từ 1 đến 5"}), 400
    image_bytes = request.data
    if not image_bytes:
        return jsonify({"error": "Không có ảnh"}), 400
    success = palm_engine.register_palm(user_id, image_bytes, index)
    if success:
        return jsonify({"message": f"Đăng ký lòng bàn tay {index}/5 thành công"})
    else:
        return jsonify({"error": "Không tìm thấy bàn tay trong ảnh"}), 400

@app.route("/api/users/<user_id>/palm/done", methods=["POST"])
def palm_done(user_id):
    palm_engine.load_all_palms()
    return jsonify({"message": "Reload palm thành công"})

@app.route("/api/users/<user_id>/face/image", methods=["GET"])
def get_face_image(user_id):
    user_dir = USERS_DIR / user_id
    index    = request.args.get("index", 1, type=int)
    fname    = f"face_{index}.jpg"
    if not (user_dir / fname).exists():
        return jsonify({"error": "Không có ảnh"}), 404
    return send_from_directory(str(user_dir), fname)

@app.route("/api/strangers", methods=["GET"])
def list_strangers():
    files = sorted(STRANGERS_DIR.glob("*.jpg"), reverse=True)[:50]
    return jsonify([f.name for f in files])

@app.route("/api/strangers/clear", methods=["POST"])
def clear_strangers():
    deleted = 0

    for f in STRANGERS_DIR.glob("*"):
        try:
            if f.is_file():
                f.unlink()
                deleted += 1
        except Exception as e:
            log.error(f"Delete stranger file error {f}: {e}")

    return jsonify({
        "status": "ok",
        "deleted": deleted,
        "message": f"Đã xóa {deleted} ảnh"
    })

@app.route("/api/strangers/<filename>", methods=["GET"])
def get_stranger_image(filename):
    return send_from_directory(str(STRANGERS_DIR), filename)

@app.route("/api/door/open", methods=["POST"])
def manual_open():
    log.info("Manual door open from web!")
    log.info(f"==> Đang sử dụng địa chỉ ESP32_IP: {esp32_ip}")
    threading.Thread(target=notifier.notify_access, args=("Quản trị viên", "admin", "manual_web")).start()
    
    # Gửi lệnh HTTP đến ESP32 để kích hoạt Servo
    if esp32_ip:
        opened = False
        for port in [82, 80]:
            try:
                resp = requests.get(f"http://{esp32_ip}:{port}/open", timeout=3)
                log.info(f"Sent open command to ESP32: {esp32_ip}:{port} → {resp.status_code}")
                opened = True
                break
            except Exception:
                continue
        if not opened:
            log.warning(f"Failed to send open command to ESP32 at {esp32_ip}")
    else:
        log.warning("Cannot open door: ESP32 IP not registered!")
            
    return jsonify({"status": "ok", "message": "Đã gửi lệnh mở cửa"})

@app.route("/api/door/auto_on", methods=["POST"])
def auto_on():
    global auto_detect_enabled
    auto_detect_enabled = True
    log.info("AUTO DETECT: ON (server-side)")
    # Cũng gửi cho ESP32 nếu có thể (phụ trợ)
    if esp32_ip:
        try:
            requests.get(f"http://{esp32_ip}:82/auto_on", timeout=2)
        except Exception:
            pass
    return jsonify({"status": "ok"})

@app.route("/api/door/auto_off", methods=["POST"])
def auto_off():
    global auto_detect_enabled
    auto_detect_enabled = False
    log.info("AUTO DETECT: OFF (server-side) — ESP32 requests will be ignored")
    # Cũng gửi cho ESP32 nếu có thể (phụ trợ)
    if esp32_ip:
        try:
            requests.get(f"http://{esp32_ip}:82/auto_off", timeout=2)
        except Exception:
            pass
    return jsonify({"status": "ok"})

@app.route("/api/status", methods=["GET"])
def get_status():
    users     = load_users()
    strangers = list(STRANGERS_DIR.glob("*.jpg"))
    return jsonify({
        "users_count":    len(users),
        "strangers_count": len(strangers),
        "faces_loaded":   len(face_engine.known_encodings),
        "server_time":    datetime.now().isoformat()
    })

# ─── CONFIG APIs ──────────────────────────────────────────────
@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = dict(app_config)
    return jsonify(cfg)

@app.route("/api/config", methods=["POST"])
def update_config():
    global app_config
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    if "telegram_token" in data:
        app_config["telegram_token"] = data["telegram_token"]
    if "telegram_chat_id" in data:
        app_config["telegram_chat_id"] = data["telegram_chat_id"]
    if "door_time" in data:
        app_config["door_time"] = int(data["door_time"])
    save_config_to_file(app_config)
    notifier.reload()
    log.info("Config updated and saved")
    return jsonify({"message": "Đã lưu cài đặt"})

@app.route("/api/config/test_telegram", methods=["POST"])
def test_telegram():
    now = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    notifier.send(f"✅ Test từ Smart Door Lock\n🕐 {now}")
    return jsonify({"message": "Đã gửi tin nhắn test"})

# ─── TEST APIs (mô phỏng ESP32-CAM, xác thực kép Mặt+Tay) ───
VERIFY_THRESHOLD = 70  # Ngưỡng tối thiểu 70%

@app.route("/api/test/face", methods=["POST"])
def test_face():
    """Bước 1: Nhận dạng khuôn mặt (không gửi Telegram)"""
    image_bytes = request.data
    if not image_bytes:
        return jsonify({"status": "error", "message": "No image"}), 400
    result = face_engine.recognize(image_bytes)

    # Lưu ảnh người lạ nếu không nhận dạng được
    if result.get("status") == "stranger":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = STRANGERS_DIR / f"stranger_{timestamp}.jpg"
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        threading.Thread(target=notifier.notify_stranger, args=(image_bytes,)).start()

    return jsonify(result)

@app.route("/api/test/palm", methods=["POST"])
def test_palm():
    """Test nhận diện lòng bàn tay từ Web UI."""
    user_id = request.args.get("user_id", "")
    if not user_id:
        return jsonify({"status": "error", "message": "Missing user_id"}), 400
    image_bytes = request.data
    if not image_bytes:
        return jsonify({"status": "error", "message": "No image"}), 400
    result = palm_engine.verify(image_bytes, user_id)
    return jsonify(result)

@app.route("/api/test/notify_success", methods=["POST"])
def test_notify_success():
    """Gửi thông báo Telegram khi mặt xác thực thành công từ Web UI"""
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    name = data.get("name", "Unknown")
    user_id = data.get("user_id", "")
    face_conf = data.get("face_confidence", 0)
    threading.Thread(
        target=notifier.notify_access,
        args=(name, user_id, "test_face", face_conf)
    ).start()
    log.info(f"Web face verify OK: {name} (face={face_conf}%)")
    return jsonify({"message": "OK"})

@app.route("/api/test/notify_fail", methods=["POST"])
def test_notify_fail():
    """Gửi thông báo Telegram khi xác thực thất bại từ Web UI (gồm % face, palm)"""
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    name = data.get("name", "Unknown")
    face_conf = data.get("face_confidence")
    palm_conf = data.get("palm_confidence")
    reason = data.get("reason", "Lòng bàn tay không khớp")
    
    # Tính trung bình để hiển thị như người dùng mong muốn
    avg_conf = None
    if face_conf is not None and palm_conf is not None:
        avg_conf = round((face_conf + palm_conf) / 2, 1)
        
    threading.Thread(
        target=notifier.notify_palm_fail,
        args=(name, face_conf, palm_conf, avg_conf, reason)
    ).start()
    log.info(f"Web verify FAIL sent to Telegram: {name} (face={face_conf}%, palm={palm_conf}%)")
    return jsonify({"message": "OK"})

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

@app.route("/voice/<path:filename>")
def serve_voice(filename):
    """Serve file MP3 từ thư mục voice/"""
    return send_from_directory(str(BASE_DIR / "voice"), filename)

# ─── SSE EVENT SYSTEM ────────────────────────────────────────
# Danh sách các hàng đợi event, mỗi browser client một queue
_sse_subscribers = []
_sse_lock = threading.Lock()

def _push_event(event_type, data=None):
    """Push event tới tất cả SSE client đang kết nối."""
    payload = json.dumps({"type": event_type, "data": data or {}})
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)

@app.route("/api/events/stream")
def sse_stream():
    """Server-Sent Events: browser subscribe để nhận event real-time."""
    import queue
    q = queue.Queue(maxsize=20)
    with _sse_lock:
        _sse_subscribers.append(q)

    def generate():
        # Gửi heartbeat ngay khi kết nối
        yield "data: {\"type\":\"connected\"}\n\n"
        while True:
            try:
                msg = q.get(timeout=25)
                yield f"data: {msg}\n\n"
            except Exception:
                # Timeout heartbeat
                yield "data: {\"type\":\"ping\"}\n\n"
    
    def cleanup():
        with _sse_lock:
            if q in _sse_subscribers:
                _sse_subscribers.remove(q)

    resp = Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
        }
    )
    return resp

@app.route("/api/event/<event_type>", methods=["POST"])
def push_event(event_type):
    """
    ESP32 gọi endpoint này để kích hoạt âm thanh trên browser.
    event_type: motion | face_ok | face_fail | palm_ok | palm_fail
    Body JSON (tùy chọn): { "name": "...", "user_id": "...", "confidence": 90.0 }
    """
    data = request.json or {}
    log.info(f"Event: {event_type} – {data}")
    threading.Thread(target=_push_event, args=(event_type, data)).start()
    return jsonify({"status": "ok"})

# ─── CHẠY SERVER ─────────────────────────────────────────────
if __name__ == "__main__":
    import socket
    try:
        # Lấy IP LAN thực của máy
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"
    log.info("=" * 50)
    log.info("  Smart Door Lock Server")
    log.info(f"  Web UI:  http://{local_ip}:{SERVER_PORT}")
    log.info(f"  ESP32:   Nhap IP \"{local_ip}\" vao esp32_door.ino")
    log.info(f"  stream:   http://{esp32_ip}:81/stream")
    log.info("=" * 50)
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)
