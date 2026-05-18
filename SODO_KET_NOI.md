# Sơ Đồ Kết Nối Hệ Thống Smart Door (ESP32-CAM)

Dưới đây là sơ đồ đấu nối chi tiết giữa ESP32-CAM với các linh kiện ngoại vi (Màn hình LCD I2C, Cảm biến chuyển động PIR, Động cơ Servo).

> **ESP32-CAM có rất ít chân GPIO có thể dùng được**, hãy đấu nối cẩn thận đúng theo sơ đồ bên dưới. Tránh sử dụng các chân đang dùng cho thẻ SD hoặc Camera.

## 1. Màn Hình LCD 2004 (Kèm module I2C)

Sử dụng giao tiếp I2C để tiết kiệm chân.
- **GND**  ->  GND của nguồn (hoặc GND ESP32)
- **VCC**  ->  **5V** (LCD 2004 cần nguồn 5V để màn hình sáng rõ, nếu cắm 3.3V có thể rất mờ)
- **SDA**  ->  **GPIO 14** (Trên ESP32-CAM)
- **SCL**  ->  **GPIO 13** (Trên ESP32-CAM)

*(Nếu màn hình LCD I2C không hiển thị chữ, hãy lấy tua-vít vặn biến trở màu xanh dương ở đằng sau module I2C để chỉnh độ tương phản).*

## 2. Cảm Biến Chuyển Động PIR (HC-SR501 hoặc tương tự)

- **VCC**  ->  **5V** (Cực kỳ quan trọng: Cảm biến PIR HC-SR501 bắt buộc cần nguồn 5V-12V để hoạt động ổn định. Nếu cắm vào chân 3.3V của ESP32, nó sẽ nhận diện sai liên tục).
- **GND**  ->  GND
- **OUT**  ->  **GPIO 15** (Trên ESP32-CAM)

### Hướng Dẫn Xử Lý PIR Hoạt Động Không Chính Xác (Báo Ảo, Chập Chờn):
1. **Nhiễu Sóng Wi-Fi:** Ăng-ten Wi-Fi của ESP32-CAM phát sóng rất mạnh làm nhiễu mạch khuếch đại của PIR. **Giải pháp:** Đặt cảm biến PIR cách xa ESP32 ít nhất 10-15cm. Hoặc bọc giấy bạc quanh cảm biến PIR (nhớ bọc màng nilon cách điện).
2. **Nguồn Điện:** Phải cấp nguồn 5V. Nguồn yếu (qua cổng USB máy tính) có thể làm PIR nhảy loạn xạ.
3. **Chỉnh Biến Trở trên PIR:** 
   - **Biến trở Delay (Bên phải - Sx):** Vặn ngược chiều kim đồng hồ kịch tầm để giảm thời gian trễ xuống thấp nhất (khoảng 2.5s - 3s).
   - **Biến trở Sensitivity (Bên trái - Sx):** Vặn mức trung bình để tránh quá nhạy.
4. **Jumper Chế Độ:** Chuyển Jumper sang vị trí **H (Repeat Trigger)** để nó giữ trạng thái HIGH liên tục khi có người, thay vì chớp tắt.

## 3. Động Cơ Servo (Mở Cửa)

- **Dây Nâu / Đen (GND)**  ->  GND
- **Dây Đỏ (VCC)**         ->  **5V** (Servo ngốn dòng cao, nên lấy từ nguồn 5V riêng, không lấy từ ESP32)
- **Dây Cam / Vàng (Signal)** -> **GPIO 12** (Trên ESP32-CAM)

---

## Lời Khuyên Nguồn Điện (Quan Trọng)
Để hệ thống ổn định, bạn cần dùng nguồn 5V - 2A (như củ sạc điện thoại tốt hoặc nguồn tổ ong).
- Cấp 5V, GND vào mạch giảm áp / chia nguồn.
- Chia nhánh 5V, GND này ra để nuôi LCD, PIR, Servo và ESP32-CAM cùng lúc. 

*(Tuyệt đối không cấp nguồn cho Servo thông qua chân xuất ra từ ESP32, vì dòng khởi động của Servo sẽ làm sụt áp khiến ESP32 bị reset liên tục).*
