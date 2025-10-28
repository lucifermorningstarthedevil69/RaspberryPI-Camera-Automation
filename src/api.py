from flask import Blueprint, jsonify, request, Response, send_from_directory, send_file
import json
import os
import datetime
import psutil
import socket
import subprocess
import time
from src.camera import get_camera_instance
from src.ir_sensor import IRSensorMonitor
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306
import threading
import io
import re
from src.oled_display import OLEDDisplay
oled_display = OLEDDisplay() 
api = Blueprint('api', __name__)

# --- Timezone ---
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# --- Paths --- 
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LOGS_DIR = os.path.join(PROJECT_ROOT, 'test_logs')
LOGS_FILE = os.path.join(LOGS_DIR, 'test_logs.json')


# --- Globals ---
start_time = time.time()
last_time = time.time()
last_net_stats = psutil.net_io_counters()
psutil.cpu_percent(interval=None)
active_tests = {}
lock = threading.Lock()

# Assuming the IR sensor is connected to BCM pin 17
IR_SENSOR_PIN = 17
ir_monitor = IRSensorMonitor(sensor_pin=IR_SENSOR_PIN)

# --- Helper Functions ---
def get_cpu_temperature():
    """Reads the CPU temperature from the system file on a Raspberry Pi."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_milli_celsius = int(f.read().strip())
            return temp_milli_celsius / 1000.0
    except (FileNotFoundError, ValueError):
        return None

def read_logs():
    if not os.path.exists(LOGS_FILE):
        return []
    try:
        with open(LOGS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def write_logs(logs):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(LOGS_FILE, 'w') as f:
        json.dump(logs, f, indent=4)

def format_duration(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}h {m}m {s}s"

def get_video_filename_from_log(log):
    """Gets the video filename from a log entry, supporting both old and new formats."""
    if 'video_filename' in log and log['video_filename']:
        return log['video_filename']
    if 'video_path' in log and log['video_path']:
        return os.path.basename(log['video_path'])
    return None

def stop_test_internally(log_id, status, reason=None):
    with lock:
        if log_id not in active_tests:
            return
        test_info = active_tests.pop(log_id)

        ir_monitor.stop_monitoring()

        if 'timer' in test_info and test_info['timer'].is_alive():
            test_info['timer'].cancel()
        if 'stop_event' in test_info:
            test_info['stop_event'].set()
        if 'recording_thread' in test_info and test_info['recording_thread'].is_alive():
            test_info['recording_thread'].join()
        
        logs = read_logs()
        for log in logs:
            if log.get('id') == log_id and log['status'] == 'Running':
                log['status'] = status
                log['end_time'] = datetime.datetime.now(IST).isoformat()
                if reason:
                    log['failure_reason'] = reason
                break
        write_logs(logs)


# --- API Routes ---
@api.route('/test/start', methods=['POST'])
def start_test():
    with lock:
        if active_tests:
            return jsonify({'status': 'An existing test is already running'}), 409

    data = request.get_json()
    duration = int(data.get('duration'))
    sample_code = data['sample_code']
    log_id = int(time.time() * 1000)
    # Generate a filename-safe timestamp and sample code
    now = datetime.datetime.now(IST)
    datetime_str = now.strftime("%Y%m%d_%H%M%S")
    safe_sample_code = re.sub(r'[^a-zA-Z0-9_.-]', '_', sample_code)
    video_filename = f"{safe_sample_code}_{datetime_str}.mp4"
    video_path = os.path.join(LOGS_DIR, video_filename)

    
    new_log = {
        'id': log_id,
        'time': datetime.datetime.now(IST).isoformat(),
        'sample_code': data.get('sample_code'),
        'duration': duration,
        'status': 'Running',
        'video_filename': video_filename
    }

    def handle_inactivity():
        print(f"Inactivity detected, stopping test {log_id}.")
        stop_test_internally(log_id, 'Fail', reason='Weight Fallen Down!')

    camera = get_camera_instance()
    stop_event = threading.Event()
    recording_thread = threading.Thread(target=camera.start_recording, args=(video_path, stop_event))
    timer = threading.Timer(duration, stop_test_internally, args=[log_id, 'Pass'])

    active_tests[log_id] = {
        'recording_thread': recording_thread,
        'stop_event': stop_event,
        'timer': timer,
        'log': new_log
    }

    logs = read_logs()
    logs.insert(0, new_log)
    write_logs(logs)

    recording_thread.start()
    timer.start()
    ir_monitor.start_monitoring(callback=handle_inactivity)

    return jsonify({'status': 'Test started', 'log': new_log})

@api.route('/test/stop', methods=['POST'])
def stop_test():
    data = request.get_json()
    stop_test_internally(data.get('id'), data.get('status', 'Fail'))
    return jsonify({'status': 'Test stopped'})

@api.route('/test/status', methods=['GET'])
def get_test_status():
    with lock:
        if not active_tests:
            return jsonify({'running': False})
        log_info = next(iter(active_tests.values()))['log']
        return jsonify({'running': True, 'log': log_info})

@api.route('/test/logs', methods=['GET'])
def get_logs():
    return jsonify(read_logs())

@api.route('/test/logs/log/<int:log_id>', methods=['DELETE'])
def delete_log_entry(log_id):
    logs = read_logs()
    log_exists = any(l.get('id') == log_id for l in logs)
    if not log_exists:
        return jsonify({'status': 'Log not found'}), 404

    updated_logs = [l for l in logs if l.get('id') != log_id]
    write_logs(updated_logs)
    return jsonify({'status': 'Log entry deleted'})

@api.route('/test/logs/video/<int:log_id>', methods=['DELETE'])
def delete_video(log_id):
    logs = read_logs()
    log_to_update = next((l for l in logs if l.get('id') == log_id), None)
    if not log_to_update:
        return jsonify({'status': 'Log not found'}), 404

    video_filename = log_to_update.get('video_filename')
    if video_filename:
        video_path = os.path.join(LOGS_DIR, video_filename)
        if os.path.exists(video_path):
            os.remove(video_path)

        log_to_update['video_filename'] = None
        write_logs(logs)
        return jsonify({'status': 'Video deleted'})
    else:
        return jsonify({'status': 'No video found for this log'}), 404


@api.route('/test/logs/download/<int:log_id>')
def download_log_txt(log_id):
    logs = read_logs()
    log_data = next((l for l in logs if l.get('id') == log_id), None)
    if not log_data:
        return jsonify({'status': 'Log not found'}), 404

    log_string = "Test Log Details\n==================\n"

    # Time
    time_str = log_data.get('time')
    if time_str:
        try:
            time_str = datetime.datetime.fromisoformat(time_str).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass # keep original
    log_string += f"Time: {time_str or 'N/A'}\n"

    # Sample Code
    log_string += f"Sample Code: {log_data.get('sample_code', 'N/A')}\n"

    # Duration
    log_string += "Duration:\n"
    set_duration = log_data.get('duration')
    if set_duration is not None:
        log_string += f"  Set Duration: {format_duration(set_duration)}\n"
    else:
        log_string += "  Set Duration: N/A\n"

    # Actual Duration (if applicable)
    status = log_data.get('status')
    if status == 'Fail' and log_data.get('time') and log_data.get('end_time'):
        try:
            start_dt = datetime.datetime.fromisoformat(log_data['time'])
            end_dt = datetime.datetime.fromisoformat(log_data['end_time'])
            actual_duration_seconds = int((end_dt - start_dt).total_seconds())
            log_string += f"  Actual Duration: {format_duration(actual_duration_seconds)}\n"
        except (ValueError, TypeError):
            pass
    
    # Status
    log_string += f"Status: {status or 'N/A'}\n"
    # Failure Reason
    if log_data.get('failure_reason'):
        log_string += f"Failure Reason: {log_data['failure_reason']}\n"

    # End Time
    end_time_str = log_data.get('end_time')
    if end_time_str:
        try:
            end_time_str = datetime.datetime.fromisoformat(end_time_str).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass # keep original
        log_string += f"End Time: {end_time_str}\n"

    sample_code = log_data.get('sample_code', 'UnknownSample')
    time_str = log_data.get('time', '')
    safe_sample_code = re.sub(r'[^a-zA-Z0-9_.-]', '_', sample_code)
    safe_time = ''
    if time_str:
        try:
            dt_obj = datetime.datetime.fromisoformat(time_str)
            safe_time = dt_obj.strftime("%Y%m%d_%H%M%S")
        except ValueError:
             safe_time = time_str.replace(':', '-').replace(' ', '_')

    download_filename = f"log_{safe_sample_code}_{safe_time}.txt"

    return send_file(
        io.BytesIO(log_string.encode('utf-8')),
        as_attachment=True,
        download_name=download_filename,
        mimetype='text/plain'
    )

@api.route('/test/logs/video/<int:log_id>', methods=['GET'])
def download_video(log_id):
    logs = read_logs()
    log_to_download = next((l for l in logs if l.get('id') == log_id), None)
    if not log_to_download:
        return jsonify({'status': 'Log not found'}), 404

    video_filename = log_to_download.get('video_filename')
    if not video_filename:
        return jsonify({'status': 'Video not found for this log'}), 404

    video_path = os.path.join(LOGS_DIR, video_filename)
    if not os.path.exists(video_path):
        return jsonify({'status': 'Video file not found'}), 404

    return send_file(video_path, as_attachment=True)


@api.route('/camera/feed')
def camera_feed():
    return Response(get_camera_instance().video_feed(), mimetype='multipart/x-mixed-replace; boundary=frame')

@api.route('/camera/release', methods=['POST'])
def release_camera():
    """Releases the camera for the live feed, without affecting recordings."""
    instance = get_camera_instance()
    if instance:
        instance.release()
        return jsonify({'status': 'Camera feed stopped.'})
    return jsonify({'status': 'Camera not initialized.'}), 500
    
@api.route('/shutdown', methods=['POST'])
def shutdown():
    try:
        if oled_display and oled_display.is_active:
            oled_display.stop_status_updates()
            oled_display.clear()
            # Center the text
            text = "Shutting down..."
            font = oled_display.font
            text_width = font.getbbox(text)[2]
            x = (oled_display.WIDTH - text_width) // 2
            oled_display.draw.text((x, 24), text, font=font, fill=255)
            oled_display.device.image(oled_display.image)
            oled_display.device.show()
        
        # Execute shutdown and capture output
        result = subprocess.run(
            ['sudo', 'shutdown', '-h', 'now'],
            capture_output=True,
            text=True
        )

        # If shutdown command requires a password, stderr will contain a message.
        if result.returncode != 0 and 'password' in result.stderr.lower():
            error_message = "Permission denied. The web server user needs sudo privileges for shutdown."
            print(f"Shutdown Error: {result.stderr}")
            return jsonify({"status": "error", "message": error_message}), 403 # Forbidden

        return jsonify({"status": "success", "message": "Shutdown command issued."})

    except Exception as e:
        error_message = f"An unexpected error occurred during shutdown: {e}"
        print(error_message)
        return jsonify({"status": "error", "message": error_message}), 500


@api.route("/stats")
def stats():
    global last_net_stats, last_time
    hostname = socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip_address = s.getsockname()[0]
    except Exception:
        ip_address = '127.0.0.1'
    finally:
        s.close()

    uptime_seconds = time.time() - start_time
    uptime_str = f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m {int(uptime_seconds % 60)}s"
    cpu_usage = psutil.cpu_percent(interval=0.1)
    cpu_temp = get_cpu_temperature()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    current_net_stats = psutil.net_io_counters()
    time_delta = time.time() - last_time
    upload_speed = ((current_net_stats.bytes_sent - last_net_stats.bytes_sent) * 8) / (time_delta * 1024 * 1024) if time_delta > 0 else 0
    download_speed = ((current_net_stats.bytes_recv - last_net_stats.bytes_recv) * 8) / (time_delta * 1024 * 1024) if time_delta > 0 else 0
    last_net_stats = current_net_stats
    last_time = time.time()

    return jsonify(
        hostname=hostname, ip=ip_address, uptime=uptime_str,
        cpu_usage=cpu_usage, cpu_temp=cpu_temp,
        mem_used=mem.used, mem_total=mem.total, memory_usage=mem.percent,
        disk_used=disk.used, disk_total=disk.total, disk_usage=disk.percent,
        net_upload_speed=upload_speed, net_download_speed=download_speed
    )
