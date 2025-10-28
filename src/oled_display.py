
import time
import board
import busio
import gpiozero
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306
import subprocess
import threading

class OLEDDisplay:
    def __init__(self, i2c_port=1, i2c_address=0x3C):
        print("Initializing OLEDDisplay...")
        self.is_active = False
        self.device = None
        try:
            self.WIDTH = 128
            self.HEIGHT = 64
            self.i2c = board.I2C()
            time.sleep(0.1)
            self.device = adafruit_ssd1306.SSD1306_I2C(self.WIDTH, self.HEIGHT, self.i2c, addr=i2c_address)
            self.is_active = True
            self.image = Image.new('1', (self.WIDTH, self.HEIGHT))
            self.draw = ImageDraw.Draw(self.image)
            self.clear()
            print("OLED display initialized successfully.")
            try:
                self.font = ImageFont.truetype('src/PixelOperator.ttf', 16)
            except IOError:
                print("Font file not found. Using default font.")
                self.font = ImageFont.load_default()
            self._stop_event = threading.Event()
            self._update_thread = None
        except Exception as e:
            print(f"Failed to initialize OLED display: {e}")

    def display_initializing(self):
        if not self.is_active:
            return
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), outline=0, fill=0)
        self.draw.text((0, 24), "System Initializing...", font=self.font, fill=255)
        self.device.image(self.image)
        self.device.show()

    def _update_status_loop(self):
        while not self._stop_event.is_set():
            self.display_system_status()
            time.sleep(1.0)

    def start_status_updates(self):
        if not self.is_active or (self._update_thread and self._update_thread.is_alive()):
            return
        self._stop_event.clear()
        self._update_thread = threading.Thread(target=self._update_status_loop)
        self._update_thread.daemon = True
        self._update_thread.start()

    def stop_status_updates(self):
        if self._update_thread and self._update_thread.is_alive():
            self._stop_event.set()
            self._update_thread.join()

    def display_system_status(self):
        if not self.is_active:
            return
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), outline=0, fill=0)
        try:
            cmd = "hostname -I | cut -d\' \' -f1"
            IP = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            cmd = "top -bn1 | grep 'Cpu(s)' | awk '{print 100 - $8}'"
            CPU = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            cmd = "free -m | awk 'NR==2{printf \"%.1f %.1f %.1f\", $3/1024,$2/1024,($3/$2)*100}'"
            MemUsage = subprocess.check_output(cmd, shell=True)
            mem_parts = MemUsage.decode('utf-8').strip().split()
            mem_used_gb = mem_parts[0]
            mem_total_gb = mem_parts[1]
            mem_percent = mem_parts[2]
            mem_display = f"Mem: {mem_used_gb}/{mem_total_gb}GB {mem_percent}%"
            cmd = "df -h | awk '$NF==\"/\"{printf \"Disk: %d/%dGB %s\", $3,$2,$5}'"
            Disk = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            cmd = "vcgencmd measure_temp |cut -f 2 -d '='"
            Temp = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            self.draw.text((0, 0), "IP: " + IP, font=self.font, fill=255)
            self.draw.text((0, 16), "CPU: "+ str(CPU) + "%", font=self.font, fill=255)
            self.draw.text((80, 16), str(Temp), font=self.font, fill=255)
            self.draw.text((0, 32), mem_display, font=self.font, fill=255)
            self.draw.text((0, 48), str(Disk), font=self.font, fill=255)
        except Exception as e:
            self.draw.text((0, 0), "Error getting stats", font=self.font, fill=255)
            print(f"Error in display_system_status: {e}")
        self.device.image(self.image)
        self.device.show()

    def display_test_in_progress(self, sample_code, remaining_time, detection_count):
        if not self.is_active:
            return
        self.stop_status_updates()
        def format_time(secs):
            m, s = divmod(secs, 60)
            h, m = divmod(m, 60)
            return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), outline=0, fill=0)
        self.draw.text((0, 0), f"Sample: {sample_code}", font=self.font, fill=255)
        self.draw.text((0, 20), f"Time: {format_time(remaining_time)}", font=self.font, fill=255)
        self.draw.text((0, 40), f"Detections: {detection_count}", font=self.font, fill=255)
        self.device.image(self.image)
        self.device.show()

    def display_test_result(self, status, duration):
        if not self.is_active:
            return
        def format_duration(seconds):
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            return f"{h}h {m}m {s:.0f}s"
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), outline=0, fill=0)
        self.draw.text((0, 0), "Test Finished", font=self.font, fill=255)
        self.draw.text((0, 20), f"Status: {status}", font=self.font, fill=255)
        self.draw.text((0, 40), f"Duration: {format_duration(duration)}", font=self.font, fill=255)
        self.device.image(self.image)
        self.device.show()
        time.sleep(10)
        self.start_status_updates()

    def clear(self):
        if not self.is_active:
            return
        self.draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), outline=0, fill=0)
        self.device.image(self.image)
        self.device.show()

    def close(self):
        if not self.is_active:
            return
        self.stop_status_updates()
        self.clear()
        print("OLED display resources released.")
