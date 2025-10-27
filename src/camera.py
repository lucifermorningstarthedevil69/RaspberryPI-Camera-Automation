
import io
import os
import time
import subprocess
from threading import Condition, Lock, Thread
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder, H264Encoder
from picamera2.outputs import FileOutput

# --- FFmpeg Conversion Utility ---
def _convert_h264_to_mp4(h264_file, mp4_file, delete_h264=True):
    """Converts an H.264 file to MP4 using ffmpeg and runs in a background thread."""
    def convert():
        print(f"Starting conversion: {h264_file} -> {mp4_file}")
        try:
            command = [
                'ffmpeg',
                '-i', h264_file,
                '-c:v', 'copy',  # Fast, no re-encoding
                '-y',            # Overwrite if exists
                mp4_file
            ]
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.returncode == 0:
                print(f"Successfully converted to {mp4_file}")
                if delete_h264:
                    os.remove(h264_file)
                    print(f"Deleted temporary file {h264_file}")
            else:
                print(f"ffmpeg error converting {h264_file}: {result.stderr}")
        except Exception as e:
            print(f"Error during video conversion: {e}")

    thread = Thread(target=convert)
    thread.daemon = True
    thread.start()


# --- Camera Streaming and Control ---
class StreamingOutput(io.BufferedIOBase):
    """A thread-safe, in-memory stream for the camera encoder."""
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

class Camera:
    """A singleton-managed class to control the PiCamera, providing both a
    live MJPEG stream and H.264 video recording with background MP4 conversion."""
    def __init__(self, width=1920, height=1080):
        self.picam2 = Picamera2()
        self.config = self.picam2.create_video_configuration(
            main={"size": (width, height)},
            lores={"size": (640, 480), "format": "YUV420"}, 
            encode="main"
        )
        self.picam2.configure(self.config)

        self.streaming_output = StreamingOutput()
        self.stream_encoder = JpegEncoder()
        self.record_encoder = H264Encoder(bitrate=10000000)
        self.is_streaming = False
        self.is_recording = False

    def start_streaming(self):
        """Starts the MJPEG encoder on the low-resolution stream."""
        if self.is_streaming: return
        try:
            self.picam2.start_encoder(self.stream_encoder, FileOutput(self.streaming_output), name='lores')
            self.is_streaming = True
            print("Camera streaming started.")
        except Exception as e:
            print(f"Failed to start streaming encoder: {e}")

    def video_feed(self):
        """Generator that yields JPEG frames for the live feed."""
        if not self.is_streaming: self.start_streaming()
        while self.is_streaming:
            with self.streaming_output.condition:
                self.streaming_output.condition.wait()
                frame = self.streaming_output.frame
            if frame: yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    def release(self):
        """Stops the live feed without affecting recording."""
        if not self.is_streaming: return
        try:
            self.picam2.stop_encoder(self.stream_encoder)
            self.is_streaming = False
            print("Camera streaming stopped.")
        except Exception as e:
            print(f"Error stopping stream encoder: {e}")

    def start_recording(self, filepath, stop_event):
        """Records video to an H.264 file and converts it to MP4 on completion."""
        if self.is_recording: return
        
        h264_path = filepath.replace('.mp4', '.h264')
        
        try:
            self.picam2.start_encoder(self.record_encoder, h264_path, name='main')
            self.is_recording = True
            print(f"Started recording to {h264_path}")
            
            while not stop_event.is_set():
                time.sleep(0.1)

        except Exception as e:
            print(f"Failed to start recording: {e}")
        finally:
            if self.is_recording:
                self.picam2.stop_encoder(self.record_encoder)
                self.is_recording = False
                print(f"Stopped recording to {h264_path}.")
                # Start background conversion to MP4
                _convert_h264_to_mp4(h264_path, filepath)

    def shutdown(self):
        """Stops all camera activity and releases the hardware."""
        self.release()
        if self.is_recording: self.picam2.stop_encoder(self.record_encoder)
        self.picam2.stop()
        print("Camera shut down.")

# --- Singleton Instance Management ---
_camera_instance = None
_camera_lock = Lock()

def get_camera_instance():
    """Provides a thread-safe, global singleton camera instance."""
    global _camera_instance
    with _camera_lock:
        if _camera_instance is None:
            print("Initializing camera for the first time...")
            # Check for ffmpeg before initializing
            try:
                subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except FileNotFoundError:
                print("\n*** WARNING: ffmpeg is not installed! ***")
                print("Video recordings will be saved as .h264 and will not be playable in the browser.")
                print("Install it with: sudo apt-get install ffmpeg\n")
            
            try:
                _camera_instance = Camera()
                _camera_instance.picam2.start()
            except Exception as e:
                print(f"FATAL: Could not initialize camera: {e}")
                _camera_instance = None
    return _camera_instance
