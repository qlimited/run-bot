# CookieRun Classic Bot UI

GUI สำหรับควบคุม CookieRun Classic Bot หลายอุปกรณ์ผ่านเบราว์เซอร์ในเครื่อง แสดงภาพหน้าจอ สถานะ ADB/Bot ด่านล่าสุด บันทึกการทำงาน และแจ้งเตือน

โค้ด Bot ต้นฉบับอยู่ใน Git submodule `bot/` ที่ตรึงเวอร์ชันไว้ ส่วน GUI อยู่ใน `gui/` ข้อมูลอุปกรณ์ถูกเก็บเฉพาะในเครื่องที่ `gui/devices.json` และไม่ถูก commit

## ติดตั้ง

ต้องมี Python, ADB ใน `PATH` และอุปกรณ์ที่ตั้งความละเอียดจอ 1280 × 720

```bash
git clone --recurse-submodules https://github.com/qlimited/run-bot.git
cd run-bot
python3.9 -m pip install -r requirements.txt
python3.9 gui/server.py
```

หาก clone มาแล้วโดยไม่ใช้ `--recurse-submodules` ให้รัน `git submodule update --init` ก่อนเปิด GUI ใช้ Python interpreter ตัวเดียวกันในการติดตั้ง dependencies และเปิดเซิร์ฟเวอร์ บน macOS สามารถดับเบิลคลิก `gui/launch.command` ได้

เปิด [http://127.0.0.1:8766/](http://127.0.0.1:8766/) เพื่อใช้งาน GUI หากพอร์ตนี้ถูกใช้แล้ว ให้รัน `python3.9 gui/server.py --port 8768` ตัวอย่างการใช้งานแต่ละส่วนอยู่ใน [gui/README.md](gui/README.md)

GUI รับฟังเฉพาะ `127.0.0.1` การตั้งค่าอุปกรณ์และประวัติแจ้งเตือนของเบราว์เซอร์ไม่ถูกส่งขึ้น GitHub
