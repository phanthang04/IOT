import sqlite3
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet
import logging

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "smartdoor.db"
KEY_PATH = DATA_DIR / "secret.key"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Khởi tạo khóa mã hóa AES (Fernet)
if not KEY_PATH.exists():
    key = Fernet.generate_key()
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    log.info("Da tao khoa ma hoa bao mat moi.")
else:
    with open(KEY_PATH, "rb") as f:
        key = f.read()

cipher = Fernet(key)

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode: cho phép đọc và ghi đồng thời, tốt hơn nhiều với Flask multi-thread
    conn.execute("PRAGMA journal_mode=WAL")
    # Bật foreign key cascade delete
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Bảng config
    c.execute('''
        CREATE TABLE IF NOT EXISTS config (
            id TEXT PRIMARY KEY,
            val_text TEXT
        )
    ''')
    
    # Bảng users
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            role TEXT,
            created TEXT
        )
    ''')
    
    # Bảng hình ảnh mã hóa
    c.execute('''
        CREATE TABLE IF NOT EXISTS secure_images (
            user_id TEXT,
            type TEXT,
            index_num INTEGER,
            data BLOB,
            PRIMARY KEY (user_id, type, index_num),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# --- Các hàm config ---
def get_config_val(key_name, default_val):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT val_text FROM config WHERE id = ?", (key_name,))
    row = c.fetchone()
    conn.close()
    if row:
        return row['val_text']
    return default_val

def set_config_val(key_name, val):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (id, val_text) VALUES (?, ?)", (key_name, str(val)))
    conn.commit()
    conn.close()

# --- Các hàm user ---
def load_users_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    rows = c.fetchall()
    conn.close()
    return {row['id']: dict(row) for row in rows}

def save_user_db(user_id, info):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO users (id, name, phone, role, created) 
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, info.get('name',''), info.get('phone',''), info.get('role','user'), info.get('created','')))
    conn.commit()
    conn.close()

def delete_user_db(user_id):
    conn = get_db()
    c = conn.cursor()
    # CASCADE sẽ tự xóa secure_images, nhưng xóa thủ công để chắc chắn
    c.execute("DELETE FROM secure_images WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- Các hàm ảnh mã hóa ---
def save_encrypted_image(user_id, img_type, index_num, image_bytes):
    """Lưu ảnh mã hóa. Nếu đã có cùng user+type+index thì ghi đè."""
    encrypted_data = cipher.encrypt(image_bytes)
    conn = get_db()
    c = conn.cursor()
    # Dùng INSERT OR REPLACE với PRIMARY KEY (user_id, type, index_num) - đơn giản và chính xác
    c.execute('''
        INSERT OR REPLACE INTO secure_images (user_id, type, index_num, data)
        VALUES (?, ?, ?, ?)
    ''', (user_id, img_type, index_num, encrypted_data))
    conn.commit()
    conn.close()

def get_decrypted_image(user_id, img_type, index_num):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT data FROM secure_images WHERE user_id = ? AND type = ? AND index_num = ?", 
              (user_id, img_type, index_num))
    row = c.fetchone()
    conn.close()
    if row:
        return cipher.decrypt(row['data'])
    return None

def count_user_images(user_id, img_type):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM secure_images WHERE user_id = ? AND type = ?", (user_id, img_type))
    row = c.fetchone()
    conn.close()
    return row['cnt'] if row else 0

def get_all_user_images(user_id, img_type):
    images = []
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT data, index_num FROM secure_images WHERE user_id = ? AND type = ?", (user_id, img_type))
    rows = c.fetchall()
    conn.close()
    for row in rows:
        try:
            images.append({
                'index_num': row['index_num'],
                'bytes': cipher.decrypt(row['data'])
            })
        except Exception as e:
            log.error(f"Decrypt error for {user_id}/{img_type}/{row['index_num']}: {e}")
    return images
