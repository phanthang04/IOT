# 🔐 SMART DOOR LOCK - Hướng Dẫn Lắp Ráp & Cài Đặt

## 📐 SƠ ĐỒ ĐẤU DÂY

```
                    ┌─────────────────────────────────────┐
                    │          ESP32-CAM (AI-Thinker)      │
                    │                                      │
  PIR Sensor ──────►│ GPIO12   GPIO13 ──────────── Servo   │
  (Signal)          │                                SG90  │
                    │          GPIO14 ────────── Relay 5V  │
                    │                               │      │
                    │          GPIO4  ──── Flash LED│      │
                    │                               │      │
                    │          GND ─────────────── GND     │
                    │          5V  ─────────────── VCC     │
                    └─────────────────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 🔌 KẾT NỐI CHI TIẾT

### 1. PIR Motion Sensor (HC-SR501)
```
PIR HC-SR501          ESP32-CAM
─────────────         ─────────
VCC     ──────────►   5V
GND     ──────────►   GND
OUT     ──────────►   GPIO12
```
> ⚠️ Vặn núm điều chỉnh: Sensitivity MAX, Time MIN (delay ngắn nhất)

---

### 2. Servo Motor (SG90 hoặc MG996R)
```
Servo                 ESP32-CAM
─────────────         ─────────
VCC (đỏ)  ──────────► 5V (dùng nguồn ngoài nếu MG996R)
GND (nâu) ──────────► GND
Signal(cam)──────────► GPIO13
```
> ⚠️ SG90 dùng 5V OK. MG996R cần nguồn 6V riêng, dùng chung GND với ESP32.

**Gắn servo vào khóa:**
- 0°  = Vị trí khóa (chốt vào)
- 90° = Vị trí mở (chốt ra)
- Dùng thanh gắn servo (horn) nối với thanh trượt của khóa

---

### 3. Relay Module (5V)
```
Relay Module          ESP32-CAM
─────────────         ─────────
VCC     ──────────►   5V
GND     ──────────►   GND
IN      ──────────►   GPIO14

Relay Module          Khóa Chốt Điện
─────────────         ─────────────────
COM     ──────────►   Dây nguồn khóa (+)
NO      ──────────►   (Thường mở - cấp điện = mở)
                      (Dùng NC nếu muốn ngược lại)
```
> 💡 Relay HIGH = bật. Chốt điện thường dùng 12V DC, relay đóng cấp điện = mở.

---

### 4. Sơ đồ tổng thể nguồn
```
Adapter 12V DC
    │
    ├──► Relay COM ──► Khóa chốt điện 12V
    │
    └──► Mạch giảm áp 5V ──► ESP32-CAM, Servo, PIR, Relay VCC
```
> Dùng module giảm áp LM2596 hoặc XL4016 để hạ 12V xuống 5V

---

## 📦 DANH SÁCH LINH KIỆN

| STT | Linh kiện           | Số lượng | Ghi chú                    |
|-----|---------------------|----------|----------------------------|
| 1   | ESP32-CAM AI-Thinker| 1        | Module chính               |
| 2   | Servo SG90          | 1        | Cho khóa nhỏ               |
| 3   | Relay 5V 10A        | 1        | Cho chốt điện              |
| 4   | PIR HC-SR501        | 1        | Cảm biến chuyển động       |
| 5   | Chốt điện 12V       | 1        | Electric Door Strike       |
| 6   | Adapter 12V 2A      | 1        | Nguồn chính                |
| 7   | LM2596 giảm áp      | 1        | 12V → 5V                   |
| 8   | Dây cắm breadboard  | 20       | Đấu nối                    |
| 9   | Hộp nhựa IP65       | 1        | Chống nước cho ngoài trời  |
| 10  | FTDI FT232 USB-TTL  | 1        | Nạp code cho ESP32-CAM     |

---

## 💻 CÀI ĐẶT PHẦN MỀM

### Bước 1: Cài Arduino IDE + thư viện ESP32

```bash
# 1. Mở Arduino IDE → File → Preferences
# 2. Thêm vào "Additional Boards Manager URLs":
https://dl.espressif.com/dl/package_esp32_index.json

# 3. Tools → Board → Boards Manager → Tìm "esp32" → Install
# 4. Cài thư viện:
# Sketch → Include Library → Manage Libraries
# - ESP32Servo
# - ArduinoJson
```

### Bước 2: Nạp code ESP32-CAM

```
Kết nối FTDI:
FTDI    ESP32-CAM
─────   ─────────
VCC  → 5V
GND  → GND
TX   → U0R (GPIO3)
RX   → U0T (GPIO1)
GND  → IO0 (kéo xuống GND khi nạp!)

Sau khi nạp xong: rút dây IO0 khỏi GND, bấm RST
```

**Sửa file `.ino` trước khi nạp:**
```cpp
const char* WIFI_SSID     = "TÊN_WIFI_NHÀ_BẠN";
const char* WIFI_PASSWORD = "MẬT_KHẨU_WIFI";
const char* SERVER_URL    = "http://192.168.1.100:5000"; // IP máy tính
```

---

### Bước 3: Cài Python Server

```bash
# Yêu cầu: Python 3.8+, pip

# Windows:
pip install -r requirements.txt

# Linux/Mac:
pip3 install -r requirements.txt

# Có thể cần cài dlib trước:
# Windows: pip install dlib
# Ubuntu: sudo apt-get install cmake libdlib-dev
#         pip3 install dlib face_recognition
```

**Lấy Telegram Bot Token:**
1. Nhắn tin với @BotFather trên Telegram
2. Gõ /newbot → đặt tên → lấy token
3. Nhắn tin với bot của bạn
4. Vào: https://api.telegram.org/bot{TOKEN}/getUpdates
5. Lấy chat_id từ kết quả JSON

**Sửa `server.py`:**
```python
TELEGRAM_TOKEN   = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
TELEGRAM_CHAT_ID = "-1001234567890"  # ID nhóm hoặc ID cá nhân
```

### Bước 4: Chạy server

```bash
cd server/
python server.py

# Output:
# 🚀 Smart Door Server đang khởi động...
# 📡 Địa chỉ: http://0.0.0.0:5000
```

**Mở Web UI:** `http://localhost:5000`

---

## 🌐 HƯỚNG DẪN SỬ DỤNG WEB UI

### Thêm người dùng:
1. Vào tab **Người dùng** → Nhấn **Thêm người dùng**
2. Điền tên, số điện thoại → Tạo
3. Nhấn **Đăng ký** ở cột Khuôn mặt → Chụp ảnh hoặc upload
4. Nhấn **Đăng ký** ở cột Lòng bàn tay → Upload ảnh lòng bàn tay

### Quy trình mở cửa tự động:
```
PIR phát hiện người
      │
      ▼
ESP32-CAM chụp ảnh khuôn mặt
      │
      ▼
Gửi ảnh lên Python Server
      │
      ├─ Không nhận ra ──► Chụp ảnh flash ──► Gửi Telegram cảnh báo
      │
      └─ Nhận ra ──► Yêu cầu quét lòng bàn tay (8 giây)
                          │
                          ├─ Không khớp ──► Từ chối + cảnh báo Telegram
                          │
                          └─ Khớp ──► Mở cửa (servo + relay)
                                           │
                                           ▼
                                   Thông báo Telegram ✅
                                   Tự đóng sau 5 giây
```

---

## 🔧 TROUBLESHOOTING

### ESP32-CAM không kết nối WiFi
- Kiểm tra SSID/Password trong code
- ESP32-CAM chỉ hỗ trợ WiFi 2.4GHz (không phải 5GHz)
- Đảm bảo nguồn 5V đủ dòng (≥1A)

### Camera không chụp được ảnh
- Kiểm tra jumper PSRAM (phải có PSRAM)
- Thử giảm FRAMESIZE xuống FRAMESIZE_QVGA

### face_recognition cài lỗi
```bash
# Ubuntu/Debian:
sudo apt-get install build-essential cmake
sudo apt-get install libopenblas-dev liblapack-dev
pip3 install dlib
pip3 install face_recognition

# Windows: Dùng conda
conda install -c conda-forge dlib
pip install face_recognition
```

### Servo giật mạnh khi cấp điện
- Dùng tụ 100µF song song với nguồn servo
- Dùng nguồn riêng 5V cho servo

---

## 📁 CẤU TRÚC THƯ MỤC

```
smart_door/
├── esp32_cam/
│   └── esp32_door.ino          ← Nạp vào ESP32-CAM
└── server/
    ├── server.py               ← Chạy trên máy tính/Raspberry Pi
    ├── requirements.txt
    ├── static/
    │   └── index.html          ← Web UI quản lý
    └── data/                   ← Tự tạo khi chạy
        ├── users/              ← Ảnh khuôn mặt
        ├── palms/              ← Ảnh lòng bàn tay
        ├── strangers/          ← Ảnh người lạ
        ├── logs/               ← Log hệ thống
        └── users.json          ← Database người dùng
```
