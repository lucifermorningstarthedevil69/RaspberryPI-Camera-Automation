from flask import Blueprint, jsonify, request, Response, send_from_directory, send_file
import os
import re
import io
import time
import json
import zipfile
import socket
import psutil
import threading
import datetime
from src.camera import get_camera_instance

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


# --- Helper Functions ---
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

def stop_test_internally(log_id, status):
    with lock:
        if log_id not in active_tests:
            return
        test_info = active_tests.pop(log_id)
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
    log_id = int(time.time() * 1000)
    video_filename = f"{log_id}.mp4"
    video_path = os.path.join(LOGS_DIR, video_filename)

    new_log = {
        'id': log_id,
        'time': datetime.datetime.now(IST).isoformat(),
        'sample_code': data.get('sample_code'),
        'duration': duration,
        'status': 'Running',
        'video_filename': video_filename
    }

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

@api.route('/test/logs/<int:log_id>', methods=['DELETE'])
def delete_log(log_id):
    logs = read_logs()
    log_to_delete = next((l for l in logs if l.get('id') == log_id), None)
    if not log_to_delete:
        return jsonify({'status': 'Log not found'}), 404

    video_filename = get_video_filename_from_log(log_to_delete)
    if video_filename:
        video_path = os.path.join(LOGS_DIR, video_filename)
        if os.path.exists(video_path):
            os.remove(video_path)
            
    updated_logs = [l for l in logs if l.get('id') != log_id]
    write_logs(updated_logs)
    return jsonify({'status': 'Log deleted'})

@api.route('/download/package/<int:log_id>')
def download_package(log_id):
    logs = read_logs()
    log_data = next((l for l in logs if l.get('id') == log_id), None)
    if not log_data:
        return jsonify({'status': 'Log not found'}), 404

    video_filename = get_video_filename_from_log(log_data)
    if not video_filename:
        return jsonify({'status': 'Video file reference not found in log'}), 404

    video_path = os.path.join(LOGS_DIR, video_filename)
    if not os.path.exists(video_path):
        return jsonify({'status': 'Video file is missing from disk'}), 404

    # Build human readable log text
    log_string = "Test Log Details\n==================\n"
    display_data = log_data.copy()

    # Format time and duration nicely
    for key, value in display_data.items():
        if key in ['time', 'end_time'] and value:
            try:
                dt = datetime.datetime.fromisoformat(value)
                display_data[key] = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        elif key == 'duration' and value is not None:
            try:
                display_data[key] = format_duration(int(value))
            except Exception:
                pass

    for key, value in display_data.items():
        if key in ['video_filename', 'video_path', 'id']:
            continue
        display_key = key.replace('_', ' ').title()
        display_value = value if value is not None else 'N/A'
        log_string += f"{display_key}: {display_value}\n"

    sample_code = log_data.get('sample_code', 'UnknownSample')
    time_str = log_data.get('time', '')
    safe_sample_code = re.sub(r'[^a-zA-Z0-9_.-]', '_', sample_code)
    safe_time = ''
    if time_str:
        try:
            dt_obj = datetime.datetime.fromisoformat(time_str)
            safe_time = dt_obj.strftime("%Y%m%d_%H%M%S")
        except Exception:
            safe_time = time_str.replace(':', '-').replace(' ', '_')

    download_filename = f"{safe_sample_code}_{safe_time}.zip"

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(video_path, video_filename)
        zf.writestr(f'log_{log_id}.txt', log_string)
    memory_file.seek(0)

    return send_file(
        memory_file,
        as_attachment=True,
        download_name=download_filename,
        mimetype='application/zip'
    )

@api.route('/download/video/<int:log_id>')
def download_video(log_id):
    """
    Serve MP4 with Range support so browsers can stream/seek.
    """
    logs = read_logs()
    log_data = next((l for l in logs if l.get('id') == log_id), None)
    if not log_data:
        return jsonify({'status': 'Log not found'}), 404

    video_filename = get_video_filename_from_log(log_data)
    if not video_filename:
        return jsonify({'status': 'Video file reference not found in log'}), 404

    video_path = os.path.join(LOGS_DIR, video_filename)
    if not os.path.exists(video_path):
        return jsonify({'status': 'Video file is missing from disk'}), 404

    file_size = os.path.getsize(video_path)
    range_header = request.headers.get('Range', None)

    if not range_header:
        # no Range header -> full response (ok for direct download)
        return send_file(video_path, as_attachment=False, download_name=video_filename, mimetype='video/mp4', conditional=True)

    # parse Range header "bytes=start-end"
    m = re.match(r'bytes=(\d+)-(\d*)', range_header)
    if not m:
        return Response(status=416)

    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    if end >= file_size:
        end = file_size - 1
    if start > end:
        return Response(status=416)

    length = end - start + 1

    def generate():
        with open(video_path, 'rb') as f:
            f.seek(start)
            remaining = length
            chunk_size = 8192
            while remaining > 0:
                read_size = min(chunk_size, remaining)
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    rv = Response(generate(), status=206, mimetype='video/mp4')
    rv.headers.add('Content-Range', f'bytes {start}-{end}/{file_size}')
    rv.headers.add('Accept-Ranges', 'bytes')
    rv.headers.add('Content-Length', str(length))
    return rv

@api.route('/camera/feed')
def camera_feed():
    return Response(get_camera_instance().video_feed(), mimetype='multipart/x-mixed-replace; boundary=frame')

@api.route('/camera/release', methods=['POST'])
def release_camera():
    """Releases the camera for the live feed, without affecting recordings."""
    get_camera_instance().release()
    return jsonify({'status': 'Camera reference released for feed'})

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
        cpu_usage=cpu_usage, mem_used=mem.used, mem_total=mem.total, memory_usage=mem.percent,
        disk_used=disk.used, disk_total=disk.total, disk_usage=disk.percent,
        net_upload_speed=upload_speed, net_download_speed=download_speed
    )
