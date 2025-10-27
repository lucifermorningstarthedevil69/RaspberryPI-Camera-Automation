#stream and recording in mp4 working
import io
import time
import os
import subprocess
from datetime import datetime
from flask import Flask, Response, jsonify
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder, H264Encoder
from picamera2.outputs import FileOutput
from threading import Condition, Thread

app = Flask(__name__)

# Global variables
camera = None
recording = False
h264_encoder = None
file_output = None
current_filename = None
conversion_status = {"converting": False, "message": ""}

class StreamingOutput(io.BufferedIOBase):
    """Custom output class for streaming JPEG frames"""
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

# Initialize streaming output
stream_output = StreamingOutput()

def gen_frames():
    """Generate frames for MJPEG streaming"""
    while True:
        with stream_output.condition:
            stream_output.condition.wait()
            frame = stream_output.frame
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

def convert_h264_to_mp4(h264_file, delete_h264=True):
    """Convert H264 file to MP4 format using ffmpeg"""
    global conversion_status
    
    try:
        conversion_status["converting"] = True
        conversion_status["message"] = f"Converting {h264_file}..."
        
        mp4_file = h264_file.replace('.h264', '.mp4')
        
        # Run ffmpeg conversion
        command = [
            'ffmpeg',
            '-i', h264_file,
            '-c:v', 'copy',  # Copy video stream without re-encoding (fast)
            '-y',  # Overwrite output file if exists
            mp4_file
        ]
        
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode == 0:
            print(f"? Converted {h264_file} to {mp4_file}")
            
            # Delete original H264 file if requested
            if delete_h264 and os.path.exists(h264_file):
                os.remove(h264_file)
                print(f"? Deleted {h264_file}")
            
            conversion_status["converting"] = False
            conversion_status["message"] = f"Conversion complete: {mp4_file}"
            return True, mp4_file
        else:
            error_msg = f"FFmpeg error: {result.stderr}"
            print(f"? {error_msg}")
            conversion_status["converting"] = False
            conversion_status["message"] = error_msg
            return False, error_msg
            
    except FileNotFoundError:
        error_msg = "FFmpeg not found. Install with: sudo apt-get install ffmpeg"
        print(f"? {error_msg}")
        conversion_status["converting"] = False
        conversion_status["message"] = error_msg
        return False, error_msg
    except Exception as e:
        error_msg = f"Conversion error: {str(e)}"
        print(f"? {error_msg}")
        conversion_status["converting"] = False
        conversion_status["message"] = error_msg
        return False, error_msg

def convert_in_background(h264_file):
    """Run conversion in background thread"""
    thread = Thread(target=convert_h264_to_mp4, args=(h264_file,))
    thread.daemon = True
    thread.start()

def start_recording():
    """Start H264 video recording"""
    global recording, h264_encoder, file_output, current_filename
    
    if recording:
        return None, "Already recording"
    
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        current_filename = f"recording_{timestamp}.h264"
        
        # Create H264 encoder and file output
        h264_encoder = H264Encoder(bitrate=10000000)
        file_output = FileOutput(current_filename)
        
        # Start the H264 encoder
        camera.start_encoder(h264_encoder, file_output, name="main")
        recording = True
        
        print(f"Started recording to {current_filename}")
        return current_filename, "Recording started"
    except Exception as e:
        print(f"Error starting recording: {e}")
        return None, f"Error: {str(e)}"

def stop_recording(auto_convert=True):
    """Stop H264 video recording and optionally convert to MP4"""
    global recording, h264_encoder, file_output, current_filename
    
    if not recording:
        return False, "No recording in progress"
    
    try:
        # Stop the H264 encoder
        camera.stop_encoder(h264_encoder)
        recording = False
        
        saved_filename = current_filename
        print(f"Stopped recording: {saved_filename}")
        
        # Convert to MP4 in background
        if auto_convert:
            convert_in_background(saved_filename)
            return True, f"Recording stopped: {saved_filename}. Converting to MP4..."
        else:
            return True, f"Recording stopped: {saved_filename}"
            
    except Exception as e:
        print(f"Error stopping recording: {e}")
        return False, f"Error: {str(e)}"

@app.route('/')
def index():
    return '''
    <html>
    <head>
        <title>RPi Camera Recorder</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 20px; background: #f0f0f0; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #333; }
            img { border: 2px solid #333; margin: 20px 0; border-radius: 5px; }
            button { 
                padding: 12px 24px; 
                margin: 5px; 
                font-size: 16px; 
                cursor: pointer;
                border-radius: 5px;
                border: none;
                font-weight: bold;
                transition: all 0.3s;
            }
            button:hover { transform: scale(1.05); }
            #start { background-color: #4CAF50; color: white; }
            #stop { background-color: #f44336; color: white; }
            #convert { background-color: #2196F3; color: white; }
            #status { 
                margin-top: 20px; 
                padding: 15px; 
                font-weight: bold; 
                border-radius: 5px;
                background: #e3f2fd;
                color: #1976d2;
            }
            .files-list {
                margin-top: 20px;
                text-align: left;
                background: #fafafa;
                padding: 15px;
                border-radius: 5px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>?? Raspberry Pi Camera Recorder</h1>
            <img src="/video_feed" width="640" height="480">
            <br><br>
            <div>
                <button id="start" onclick="startRec()">?? Start Recording</button>
                <button id="stop" onclick="stopRec()">?? Stop Recording</button>
                <button id="convert" onclick="checkStatus()">?? Check Status</button>
            </div>
            <div id="status">Ready</div>
        </div>
        <script>
            function updateStatus(message) {
                document.getElementById('status').innerText = message;
            }
            
            function startRec() {
                fetch('/start_record', {method: 'POST'})
                    .then(res => res.json())
                    .then(data => {
                        updateStatus(data.message);
                    });
            }
            
            function stopRec() {
                fetch('/stop_record', {method: 'POST'})
                    .then(res => res.json())
                    .then(data => {
                        updateStatus(data.message);
                        // Auto-refresh status after 2 seconds
                        setTimeout(checkStatus, 2000);
                    });
            }
            
            function checkStatus() {
                fetch('/conversion_status')
                    .then(res => res.json())
                    .then(data => {
                        updateStatus(data.message);
                        // Keep checking if conversion is in progress
                        if (data.converting) {
                            setTimeout(checkStatus, 1000);
                        }
                    });
            }
            
            // Auto-update status every 5 seconds
            setInterval(checkStatus, 5000);
        </script>
    </body>
    </html>
    '''

@app.route('/video_feed')
def video_feed():
    """Video streaming route"""
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_record', methods=['POST'])
def start_record():
    """Start recording endpoint"""
    filename, message = start_recording()
    if filename:
        return jsonify({'status': 'success', 'message': message, 'filename': filename})
    return jsonify({'status': 'error', 'message': message})

@app.route('/stop_record', methods=['POST'])
def stop_record():
    """Stop recording endpoint (auto-converts to MP4)"""
    success, message = stop_recording(auto_convert=True)
    if success:
        return jsonify({'status': 'success', 'message': message})
    return jsonify({'status': 'error', 'message': message})

@app.route('/conversion_status')
def conversion_status_route():
    """Get current conversion status"""
    return jsonify({
        'converting': conversion_status['converting'],
        'message': conversion_status['message'] or 'No conversion in progress'
    })

@app.route('/convert_manual/<filename>', methods=['POST'])
def convert_manual(filename):
    """Manual conversion endpoint for existing H264 files"""
    if not filename.endswith('.h264'):
        return jsonify({'status': 'error', 'message': 'File must be .h264 format'})
    
    if not os.path.exists(filename):
        return jsonify({'status': 'error', 'message': f'File not found: {filename}'})
    
    convert_in_background(filename)
    return jsonify({'status': 'success', 'message': f'Conversion started for {filename}'})

if __name__ == '__main__':
    try:
        # Check if ffmpeg is installed
        try:
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            print("? FFmpeg detected")
        except FileNotFoundError:
            print("? WARNING: FFmpeg not found. Install with: sudo apt-get install ffmpeg")
            print("  H264 to MP4 conversion will not work without FFmpeg")
        
        # Initialize camera
        camera = Picamera2()
        
        # Create video configuration with main stream for recording and lores for streaming
        config = camera.create_video_configuration(
            main={"size": (1920, 1080), "format": "RGB888"},
            lores={"size": (640, 480), "format": "YUV420"},
            encode="main"
        )
        camera.configure(config)
        
        # Start JPEG encoder for streaming (uses lores stream)
        jpeg_encoder = JpegEncoder()
        camera.start_encoder(jpeg_encoder, FileOutput(stream_output), name="lores")
        
        # Start the camera
        camera.start()
        
        print("? Camera initialized successfully")
        print("? Streaming: http://<your-pi-ip>:5000")
        print("? Auto-conversion: H264 ? MP4 enabled")
        
        # Run Flask app
        app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)
        
    except Exception as e:
        print(f"? Error initializing camera: {e}")
    finally:
        if camera:
            camera.stop()
            camera.close()
