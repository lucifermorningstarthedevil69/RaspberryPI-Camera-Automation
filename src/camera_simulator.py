from PIL import Image, ImageDraw, ImageFont
import time
import os
import io

class CameraSimulator:
    def __init__(self, width=1280, height=720):
        self.width = width
        self.height = height
        self.font = self.get_font()

    def get_font(self):
        try:
            return ImageFont.truetype("arial.ttf", 40)
        except IOError:
            return ImageFont.load_default()

    def generate_image_bytes(self, text):
        img = Image.new('RGB', (self.width, self.height), color = 'black')
        d = ImageDraw.Draw(img)

        left, top, right, bottom = d.textbbox((0,0), text, font=self.font)
        text_width = right - left
        text_height = bottom - top

        position = ((self.width - text_width) / 2, (self.height - text_height) / 2)
        d.text(position, text, fill=(255,255,255), font=self.font)

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG')
        return img_byte_arr.getvalue()

    def video_feed(self):
        """Generator function for video streaming."""
        while True:
            text = time.strftime("%Y-%m-%d %H:%M:%S")
            frame = self.generate_image_bytes(text)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(1)

def video_feed_simulator():
    """Generator function for video streaming."""
    simulator = CameraSimulator()
    return simulator.video_feed()
