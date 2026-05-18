import re

with open("esp32_door.ino", "r", encoding="utf-8") as f:
    content = f.read()

# Delete functions: sendEvent, captureImage, recognizeFace, verifyPalm, alertStranger
# We can use regex to find and remove them.
content = re.sub(r'//======= GỬI EVENT ĐẾN SERVER.*?//========================================', '//========================================', content, flags=re.DOTALL)

# Delete captureImage
content = re.sub(r'camera_fb_t \*captureImage\(\) \{.*?\n\}\n', '', content, flags=re.DOTALL)

# Delete recognizeFace
content = re.sub(r'String recognizeFace\(.*?\n\}\n', '', content, flags=re.DOTALL)

# Delete verifyPalm
content = re.sub(r'String verifyPalm\(.*?\n\}\n', '', content, flags=re.DOTALL)

# Delete alertStranger
content = re.sub(r'void alertStranger\(\) \{.*?\n\}\n', '', content, flags=re.DOTALL)

# Replace loop
new_loop = """void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
    registerStreamUrl();
    return;
  }

  // Lệnh mở cửa từ web (open_handler) đã được xử lý bởi task độc lập (openDoorTask)
  // nên không cần check cờ shouldOpenDoor ở đây nữa, tránh bị block bởi PIR.

  if (isAutoDetect && digitalRead(PIR_PIN) == HIGH) {
    Serial.println("=== Motion Detected ===");

    // Gửi báo cáo chuyển động lên Server
    HTTPClient http;
    http.begin(httpClient, String(SERVER) + "/api/trigger_motion");
    http.setTimeout(3000);
    int httpCode = http.GET();
    http.end();
    
    Serial.println("Sent motion trigger to Server, Code: " + String(httpCode));

    // Đợi 10 giây để tránh gửi trùng lặp
    Serial.println("=== Wait 10s ===");
    delay(10000);
  }

  delay(100);
}
"""
content = re.sub(r'void loop\(\) \{.*', new_loop, content, flags=re.DOTALL)

# Cleanup extra empty lines
content = re.sub(r'\n{3,}', '\n\n', content)

with open("esp32_door.ino", "w", encoding="utf-8") as f:
    f.write(content)
print("done")
