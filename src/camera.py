
import cv2
import time
from threading import Lock

class Camera:
    def __init__(self, width=1280, height=720):
        self.width = width
        self.height = height
        self.camera = None
        self.lock = Lock()
        self.ref_count = 0  # Reference counter

    def acquire(self):
        """Acquires a reference to the camera, starting it if necessary."""
        with self.lock:
            if self.ref_count == 0:
                self.camera = cv2.VideoCapture(0)
                if not self.camera.isOpened():
                    self.camera = None
                    raise RuntimeError("Could not start camera.")
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.ref_count += 1

    def release(self):
        """Releases a reference, stopping the camera if it's the last reference."""
        with self.lock:
            self.ref_count -= 1
            if self.ref_count <= 0:
                if self.camera is not None:
                    self.camera.release()
                    self.camera = None
                self.ref_count = 0 # Ensure it doesn't go negative

    def get_frame(self):
        """Reads a single frame, timestamps it, and returns it as JPEG bytes."""
        with self.lock:
            if self.camera is None:
                return None
            success, frame = self.camera.read()

        if not success:
            return None

        font = cv2.FONT_HERSHEY_SIMPLEX
        text = time.strftime("%Y-%m-%d %H:%M:%S")
        text_size, _ = cv2.getTextSize(text, font, 1, 2)
        text_x = frame.shape[1] - text_size[0] - 20
        text_y = frame.shape[0] - 20
        cv2.putText(frame, text, (text_x, text_y), font, 1, (255, 255, 255), 2)

        ret, jpeg = cv2.imencode('.jpg', frame)
        return jpeg.tobytes()

    def video_feed(self):
        """Generator function that yields frames for the live video stream."""
        self.acquire()
        try:
            while True:
                frame = self.get_frame()
                if frame:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                else:
                    break
                time.sleep(1/30)
        finally:
            self.release()

    def start_recording(self, filepath, stop_event):
        """Records the camera feed to the specified file."""
        self.acquire()
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(filepath, fourcc, 20.0, (self.width, self.height))
        try:
            while not stop_event.is_set():
                with self.lock:
                    if self.camera is None:
                        break
                    success, frame = self.camera.read()
                if success:
                    out.write(frame)
                else:
                    break
        finally:
            out.release()
            self.release()

# --- Singleton Instance Management ---
_camera_instance = None
_camera_lock = Lock()

def get_camera_instance():
    """Provides a global singleton camera instance."""
    global _camera_instance
    with _camera_lock:
        if _camera_instance is None:
            _camera_instance = Camera()
        return _camera_instance
