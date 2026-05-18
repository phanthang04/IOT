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
from flask import Flask, request, jsonify, send_from_directory
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
    "door_time": "10"
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

# ─── PALM VERIFICATION ENGINE ────────────────────────────────
class PalmEngine:
    def __init__(self):
        self.orb = cv2.ORB_create(nfeatures=1500)
        self.bf  = cv2.BFMatcher(cv2.NORM_HAMMING)  # No crossCheck for ratio test

    def preprocess_palm(self, img_bgr):
        gray     = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        resized  = cv2.resize(gray, (300, 300))
        clahe    = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(resized)
        blur     = cv2.GaussianBlur(enhanced, (3, 3), 0)
        return blur

    def extract_palm_lines(self, preprocessed):
        """Trích xuất đường chỉ tay bằng adaptive threshold"""
        binary = cv2.adaptiveThreshold(
            preprocessed, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2
        )
        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        return binary

    def _match_score(self, kp1, kp2, des1, des2):
        """Lowe's ratio test với thuật toán RANSAC để loại bỏ outlier, chống nhận diện sai tay trái/phải"""
        kp1_len = len(kp1) if kp1 else 0
        if des1 is None or des2 is None or len(des1) < 4 or len(des2) < 4 or kp1_len == 0:
            return 0
        matches = self.bf.knnMatch(des1, des2, k=2)
        good = []
        for pair in matches:
            if len(pair) == 2:
                m, n = pair
                if m.distance < 0.75 * n.distance:
                    good.append(m)
        
        # Chỉ những điểm có geometry match mới tính (nhờ vậy loại bỏ được tay trái/phải do không mapping được geometry)
        if len(good) >= 4:
            src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            # Find homography and count inliers
            _, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
            if mask is not None:
                inliers = np.sum(mask)
                return inliers / max(kp1_len, 1)
                
        return len(good) / max(kp1_len, 1) if len(good) < 4 else 0

    def verify(self, user_id, image_bytes):
        db_images = db.get_all_user_images(user_id, "palm")
        if not db_images:
            return {"status": "no_palm_registered"}
        try:
            np_arr   = np.frombuffer(image_bytes, np.uint8)
            test_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if test_img is None:
                return {"status": "error", "message": "Invalid image"}
            test_proc  = self.preprocess_palm(test_img)
            test_lines = self.extract_palm_lines(test_proc)
            best_score = 0

            for img_info in db_images:
                try:
                    ref_arr = np.frombuffer(img_info['bytes'], np.uint8)
                    ref_img = cv2.imdecode(ref_arr, cv2.IMREAD_COLOR)
                    if ref_img is None:
                        continue
                except Exception:
                    continue
                    
                ref_proc  = self.preprocess_palm(ref_img)
                ref_lines = self.extract_palm_lines(ref_proc)

                # ORB matching trên ảnh gốc (texture + nếp nhăn)
                kp1, des1 = self.orb.detectAndCompute(ref_proc, None)
                kp2, des2 = self.orb.detectAndCompute(test_proc, None)
                orb_score = self._match_score(kp1, kp2, des1, des2)

                # ORB matching trên đường chỉ tay (cấu trúc đặc trưng)
                kp1l, des1l = self.orb.detectAndCompute(ref_lines, None)
                kp2l, des2l = self.orb.detectAndCompute(test_lines, None)
                line_score = self._match_score(kp1l, kp2l, des1l, des2l)

                # Combined: 50% texture + 50% palm lines
                combined = orb_score * 0.5 + line_score * 0.5
                if combined > best_score:
                    best_score = combined

            # Normalize to 0-100 confidence range
            THRESHOLD = 0.06
            confidence = round(min(best_score / 0.12 * 100, 99.9), 1)
            log.info(f"Palm score for {user_id}: {best_score:.4f} (threshold: {THRESHOLD})")

            if best_score >= THRESHOLD:
                return {"status": "verified", "confidence": confidence}
            else:
                return {"status": "failed", "confidence": confidence}
        except Exception as e:
            log.error(f"Palm verify error: {e}")
            return {"status": "error", "message": str(e)}

    def verify_all_users(self, image_bytes):
        users = load_users()
        best_result     = {"status": "no_match"}
        best_confidence = 0
        for user_id, info in users.items():
            result = self.verify(user_id, image_bytes)
            if result.get("status") == "verified":
                conf = result.get("confidence", 0)
                if conf > best_confidence:
                    best_confidence = conf
                    best_result = {
                        "status":     "verified",
                        "user_id":    user_id,
                        "name":       info["name"],
                        "confidence": conf
                    }
        return best_result

    def register_palm(self, user_id, image_bytes, index):
        try:
            np_arr  = np.frombuffer(image_bytes, np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                return False
            
            # Lưu ảnh lòng bàn tay mã hóa vào DB
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

    def notify_palm_fail(self, name):
        now_time = datetime.now().strftime("%H:%M:%S")
        now_date = datetime.now().strftime("%d/%m/%Y")
        self.send(
            f"⚠️ XÁC THỰC THẤT BẠI\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 {name}\n"
            f"Khuôn mặt OK nhưng lòng bàn tay KHÔNG KHỚP!\n"
            f"📅 Ngày: {now_date}\n"
            f"🕐 Giờ: {now_time}\n"
            f"━━━━━━━━━━━━━━━━"
        )
        
    def notify_palm_fail_detail(self, name, face_conf, palm_conf, avg_conf, reason):
        now_time = datetime.now().strftime("%H:%M:%S")
        now_date = datetime.now().strftime("%d/%m/%Y")
        self.send(
            f"⚠️ XÁC THỰC THẤT BẠI\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 {name}\n"
            f"🔴 Lý do: {reason}\n"
            f"😀 Face: {face_conf}%\n"
            f"🖐 Palm: {palm_conf}%\n"
            f"📊 Trung bình: {avg_conf}% (cần ≥ 70%)\n"
            f"📅 Ngày: {now_date}\n"
            f"🕐 Giờ: {now_time}\n"
            f"━━━━━━━━━━━━━━━━"
        )

# ─── KHỞI TẠO ────────────────────────────────────────────────
face_engine = FaceEngine()
palm_engine = PalmEngine()
notifier    = TelegramNotifier()

# ─── STREAMING CAMERA ─────────────────────────────────────────
latest_frame = None

@app.route("/api/frame", methods=["POST"])
def receive_frame():
    global latest_frame
    image_bytes = request.data
    if image_bytes:
        latest_frame = image_bytes
    return jsonify({"status": "ok"})

def gen_frames():
    global latest_frame
    while True:
        try:
            if latest_frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + latest_frame + b'\r\n')
                time.sleep(0.05)
            else:
                time.sleep(0.1)
        except GeneratorExit:
            break

@app.route("/api/stream", methods=["GET"])
def video_stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ═══════════════════════════════════════════════════════════════
#                         API ENDPOINTS
# ═══════════════════════════════════════════════════════════════

# ─── ESP32-CAM APIs ───────────────────────────────────────────
@app.route("/api/recognize/face", methods=["POST"])
def recognize_face():
    image_bytes = request.data
    if not image_bytes:
        return jsonify({"status": "error", "message": "No image"}), 400
    result = face_engine.recognize(image_bytes)
    log.info(f"Face recognition: {result}")
    return jsonify(result)

@app.route("/api/recognize/palm", methods=["POST"])
def recognize_palm():
    user_id     = request.args.get("user_id")
    image_bytes = request.data
    if not user_id or not image_bytes:
        return jsonify({"status": "error", "message": "Missing params"}), 400
    result = palm_engine.verify(user_id, image_bytes)
    log.info(f"Palm verification [{user_id}]: {result}")
    if result["status"] == "verified":
        user = get_user(user_id)
        if user:
            conf = result.get("confidence")
            threading.Thread(target=notifier.notify_access, args=(user["name"], user_id, "face+palm", conf)).start()
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

@app.route("/api/alert/palm_fail", methods=["GET"])
def alert_palm_fail():
    user_id = request.args.get("user_id")
    user = get_user(user_id)
    name = user["name"] if user else user_id
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
            "has_palm":   palm_count > 0,
            "face_count": face_count,
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
        return jsonify({"error": "Lỗi đăng ký lòng bàn tay"}), 400

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

@app.route("/api/strangers/<filename>", methods=["GET"])
def get_stranger_image(filename):
    return send_from_directory(str(STRANGERS_DIR), filename)

@app.route("/api/door/open", methods=["POST"])
def manual_open():
    log.info("Manual door open from web!")
    threading.Thread(target=notifier.notify_access, args=("Quản trị viên", "admin", "manual_web")).start()
    return jsonify({"status": "ok", "message": "Đã gửi lệnh mở cửa"})

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
    """Bước 2: Xác thực lòng bàn tay cho user_id cụ thể (không gửi Telegram)"""
    image_bytes = request.data
    user_id = request.args.get("user_id")
    if not image_bytes:
        return jsonify({"status": "error", "message": "No image"}), 400
    if user_id:
        result = palm_engine.verify(user_id, image_bytes)
    else:
        result = palm_engine.verify_all_users(image_bytes)
    return jsonify(result)

@app.route("/api/test/notify_success", methods=["POST"])
def test_notify_success():
    """Gửi thông báo Telegram khi cả mặt + tay đều xác thực thành công"""
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    name = data.get("name", "Unknown")
    user_id = data.get("user_id", "")
    face_conf = data.get("face_confidence", 0)
    palm_conf = data.get("palm_confidence", 0)
    avg_conf = round((face_conf + palm_conf) / 2, 1)
    threading.Thread(
        target=notifier.notify_access,
        args=(name, user_id, "dual_verify", avg_conf)
    ).start()
    log.info(f"Dual verify OK: {name} (face={face_conf}%, palm={palm_conf}%)")
    return jsonify({"message": "OK"})

@app.route("/api/test/notify_fail", methods=["POST"])
def test_notify_fail():
    """Gửi thông báo Telegram khi xác thực thất bại"""
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400
    name = data.get("name", "Unknown")
    face_conf = data.get("face_confidence", 0)
    palm_conf = data.get("palm_confidence", 0)
    reason = data.get("reason", "Không xác định")
    avg_conf = round((face_conf + palm_conf) / 2, 1)
    threading.Thread(
        target=notifier.notify_palm_fail_detail,
        args=(name, face_conf, palm_conf, avg_conf, reason)
    ).start()
    log.info(f"Dual verify FAILED: {name} (face={face_conf}%, palm={palm_conf}%, avg={avg_conf}%)")
    return jsonify({"message": "OK"})
