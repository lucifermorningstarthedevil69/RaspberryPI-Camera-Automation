
import os
import subprocess
from flask import Flask, send_from_directory
from src.api import api
from src.oled_display import OLEDDisplay 
oled_display = OLEDDisplay()

app = Flask(__name__, static_folder='static')

# --- Paths ---
# Define the absolute path to the directory containing video logs.
LOGS_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'test_logs')


# --- Start Camera Simulator ---
def start_camera_simulator():
    """Starts the camera simulator script in a separate process."""
    try:
        subprocess.run(["pkill", "-f", "src/camera_simulator.py"], check=False)
        python_executable = os.path.join(os.getcwd(), '.venv', 'bin', 'python')
        subprocess.Popen([python_executable, "src/camera_simulator.py"])
        print("Camera simulator started.")
    except Exception as e:
        print(f"Error starting camera simulator: {e}")


# --- App Setup ---
app.register_blueprint(api, url_prefix='/api')


# --- Main Application Routes ---
@app.route("/")
def index():
    return send_from_directory('src', 'index.html')

@app.route("/history")
def history():
    return send_from_directory('src', 'history.html')

@app.route("/system-info")
def system_info():
    return send_from_directory('src', 'system-info.html')

@app.route("/play/<filename>")
def play(filename):
    return send_from_directory('src', 'player.html')


# --- Static File and Video Routes ---
@app.route('/live_feed')
def live_feed():
    """Serves the live feed image."""
    return send_from_directory(app.static_folder, 'live_feed.png')

@app.route('/videos/<path:filename>')
def serve_video(filename):
    """Serves video files directly from the test_logs directory."""
    return send_from_directory(LOGS_DIR, filename)


# --- Main ---
if __name__ == "__main__":
    oled_display = OLEDDisplay()
    if oled_display.is_active:
        oled_display.display_initializing()
        
    start_camera_simulator()


    if oled_display.is_active:
        oled_display.start_status_updates()
        
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True, use_reloader=False)
