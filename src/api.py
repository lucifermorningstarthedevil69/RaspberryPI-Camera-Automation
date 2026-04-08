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
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

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
        'sample_type': data.get('sample_type', ''),
        'is_code': data.get('is_code', ''),
        'rating': data.get('rating', ''),
        'height': data.get('height', ''),
        'weight': data.get('weight', ''),
        'area': data.get('area', ''),
        'diameter': data.get('diameter', ''),
        'duration': duration,
        'status': 'Running',
        'video_filename': video_filename
    }

    def handle_inactivity():
        print(f"Inactivity detected, stopping test {log_id}.")
        stop_test_internally(log_id, 'Fail', reason='Weight Fallen Down!')

    camera = get_camera_instance()
    
    res_str = data.get('resolution', '1280x720')
    try:
        width, height = map(int, res_str.split('x'))
        camera.reconfigure_resolution(width, height)
    except Exception as e:
        print(f"Failed to reconfigure resolution: {e}")

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

    return jsonify({
        'status': 'Test started',
        'log': new_log,
        'server_time': datetime.datetime.now(IST).isoformat()
    })

@api.route('/test/stop', methods=['POST'])
def stop_test():
    data = request.get_json()
    stop_test_internally(data.get('id'), data.get('status', 'Fail'))
    return jsonify({'status': 'Test stopped'})

@api.route('/test/manual_result', methods=['POST'])
def save_manual_result():
    data = request.get_json()
    log_id = data.get('id')
    conductor_break = data.get('conductor_break')
    conductor_damage = data.get('conductor_damage')

    logs = read_logs()
    for log in logs:
        if log.get('id') == log_id:
            log['conductor_break'] = conductor_break
            log['conductor_damage'] = conductor_damage
            if conductor_break == 'Fail' or conductor_damage == 'Fail':
                log['status'] = 'Fail'
                if log.get('failure_reason') != 'Weight Fallen Down!':
                    log['failure_reason'] = 'Manual Inspection Failed'
            write_logs(logs)
            return jsonify({'status': 'Success', 'final_status': log['status'], 'failure_reason': log.get('failure_reason', '')})
    return jsonify({'status': 'Log not found'}), 404

@api.route('/test/status', methods=['GET'])
def get_test_status():
    with lock:
        if not active_tests:
            return jsonify({'running': False})
        log_info = next(iter(active_tests.values()))['log']
        return jsonify({
            'running': True,
            'log': log_info,
            'server_time': datetime.datetime.now(IST).isoformat()
        })

@api.route('/test/logs', methods=['GET'])
def get_logs():
    return jsonify(read_logs())

@api.route('/test/logs/log/<int:log_id>', methods=['DELETE'])
def delete_log_entry(log_id):
    logs = read_logs()
    log_to_delete = next((l for l in logs if l.get('id') == log_id), None)
    
    if not log_to_delete:
        return jsonify({'status': 'Log not found'}), 404

    # Delete associated video file if it exists
    video_filename = log_to_delete.get('video_filename')
    if video_filename:
        video_path = os.path.join(LOGS_DIR, video_filename)
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception as e:
                print(f"Error deleting video file {video_path}: {e}")

    updated_logs = [l for l in logs if l.get('id') != log_id]
    write_logs(updated_logs)
    return jsonify({'status': 'Log entry and associated video deleted'})

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
def download_log_pdf(log_id):
    logs = read_logs()
    log_data = next((l for l in logs if l.get('id') == log_id), None)
    if not log_data:
        return jsonify({'status': 'Log not found'}), 404

    # Prepare data
    sample_code = log_data.get('sample_code', 'N/A')
    time_str = log_data.get('time')
    
    date_val = "N/A"
    time_val = "N/A"
    if time_str:
        try:
            dt = datetime.datetime.fromisoformat(time_str)
            date_val = dt.strftime("%Y-%m-%d")
            time_val = dt.strftime("%H:%M:%S")
        except:
            pass
            
    # Duration logic
    set_duration = log_data.get('duration', 0)
    set_dur_str = format_duration(set_duration)
    
    actual_dur_str = "N/A"
    if log_data.get('status') == 'Fail' and log_data.get('time') and log_data.get('end_time'):
        try:
            start_dt = datetime.datetime.fromisoformat(log_data['time'])
            end_dt = datetime.datetime.fromisoformat(log_data['end_time'])
            actual_seconds = int((end_dt - start_dt).total_seconds())
            actual_dur_str = format_duration(actual_seconds)
        except:
            pass
    elif log_data.get('status') == 'Pass':
         actual_dur_str = set_dur_str # If passed, it completed

    status = log_data.get('status', 'N/A')
    failure_reason = log_data.get('failure_reason', '')
    
    # Logic for Slip Out: 
    # If the automated system caught weight fall, slip out failed.
    slip_out_result = "Fail" if failure_reason == 'Weight Fallen Down!' else "Pass"
    
    # Logic for Manual Checks
    conductor_break_result = log_data.get('conductor_break', 'N/A')
    conductor_damage_result = log_data.get('conductor_damage', 'N/A')

    final_status = "Unsatisfactory" if status == 'Fail' else "Satisfactory"

    # PDF Generation
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        alignment=1, # Center
        spaceAfter=20,
        fontSize=16,
        textColor=colors.black
    )
    
    elements.append(Paragraph("Test Report for Terminal Test Apparatus", title_style))
    elements.append(Spacer(1, 20))
    
    # Table Data
    data = [
        ["Sample Code:", sample_code],
        ["IS Code:", log_data.get('is_code', '3854:1997')],
        ["Sample Type:", log_data.get('sample_type', '')],
        ["Cross-Sectional Area:", log_data.get('area', '')],
        ["Bushing Hole Diameter:", log_data.get('diameter', '')],
        ["Rating:", log_data.get('rating', '')],
        ["Height:", log_data.get('height', '')],
        ["Weight:", log_data.get('weight', '')],
        ["Duration", f"Set Duration: {set_dur_str}"],
        ["", f"Actual Duration: {actual_dur_str}"], # Merge cell for Duration
        ["Date:", date_val],
        ["Time:", time_val],
        ["Test Report:", ""], 
        ["    a) Slip Out", slip_out_result],
        ["    b) Conductor Break near Clamping unit", conductor_break_result],
        ["    c) Conductor Damage", conductor_damage_result],
        ["Status:", final_status]
    ]

    t = Table(data, colWidths=[200, 250])
    t.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('SPAN', (0, 8), (0, 9)), # Span 'Duration' vertically
        ('SPAN', (0, 12), (1, 12)), # Span 'Test Report:' across both columns
        ('BACKGROUND', (0, 12), (1, 12), colors.lightgrey),
        ('FONTNAME', (0, 13), (0, 15), 'Helvetica'), # Make sub-items regular font instead of bold
    ]))
    
    elements.append(t)
    doc.build(elements)
    
    buffer.seek(0)
    
    clean_sample = re.sub(r'[^a-zA-Z0-9_.-]', '_', sample_code)
    clean_date = date_val.replace('-', '')
    filename = f"Report_{clean_sample}_{clean_date}.pdf"
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
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


@api.route('/test/logs/download_combined/<sample_code>')
def download_combined_pdf(sample_code):
    report_type = request.args.get('type', 'summary')
    logs = read_logs()
    
    matching_logs = [l for l in logs if l.get('sample_code') == sample_code]
    matching_logs.sort(key=lambda x: x.get('time', ''))
    
    if not matching_logs:
        return jsonify({'status': 'No logs found for this sample code'}), 404

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        alignment=1, # Center
        spaceAfter=20,
        fontSize=16,
        textColor=colors.black
    )
    
    clean_sample = re.sub(r'[^a-zA-Z0-9_.-]', '_', sample_code)
    datetime_str = datetime.datetime.now(IST).strftime("%Y%m%d_%H%M%S")

    if report_type == 'detailed':
        filename = f"Combined_Detailed_Report_{clean_sample}_{datetime_str}.pdf"
        for idx, log_data in enumerate(matching_logs):
            elements.append(Paragraph(f"Detailed Test Report #{idx+1}", title_style))
            elements.append(Spacer(1, 20))
            
            time_str = log_data.get('time')
            date_val = "N/A"
            time_val = "N/A"
            if time_str:
                try:
                    dt = datetime.datetime.fromisoformat(time_str)
                    date_val = dt.strftime("%Y-%m-%d")
                    time_val = dt.strftime("%H:%M:%S")
                except: pass

            set_duration = log_data.get('duration', 0)
            set_dur_str = format_duration(set_duration)
            actual_dur_str = "N/A"
            if log_data.get('status') == 'Fail' and log_data.get('time') and log_data.get('end_time'):
                try:
                    start_dt = datetime.datetime.fromisoformat(log_data['time'])
                    end_dt = datetime.datetime.fromisoformat(log_data['end_time'])
                    actual_seconds = int((end_dt - start_dt).total_seconds())
                    actual_dur_str = format_duration(actual_seconds)
                except: pass
            elif log_data.get('status') == 'Pass':
                 actual_dur_str = set_dur_str 

            status = log_data.get('status', 'N/A')
            failure_reason = log_data.get('failure_reason', '')
            slip_out_result = "Fail" if failure_reason == 'Weight Fallen Down!' else "Pass"
            conductor_break_result = log_data.get('conductor_break', 'N/A')
            conductor_damage_result = log_data.get('conductor_damage', 'N/A')
            final_status = "Unsatisfactory" if status == 'Fail' else "Satisfactory"

            data = [
                ["Sample Code:", sample_code],
                ["IS Code:", log_data.get('is_code', '3854:1997')],
                ["Sample Type:", log_data.get('sample_type', '')],
                ["Cross-Sectional Area:", log_data.get('area', '')],
                ["Bushing Hole Diameter:", log_data.get('diameter', '')],
                ["Rating:", log_data.get('rating', '')],
                ["Height:", log_data.get('height', '')],
                ["Weight:", log_data.get('weight', '')],
                ["Duration", f"Set Duration: {set_dur_str}"],
                ["", f"Actual Duration: {actual_dur_str}"], 
                ["Date:", date_val],
                ["Time:", time_val],
                ["Test Report:", ""], 
                ["    a) Slip Out", slip_out_result],
                ["    b) Conductor Break near Clamping unit", conductor_break_result],
                ["    c) Conductor Damage", conductor_damage_result],
                ["Status:", final_status]
            ]
            t = Table(data, colWidths=[200, 250])
            t.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 1, colors.black),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('SPAN', (0, 8), (0, 9)), 
                ('SPAN', (0, 12), (1, 12)), 
                ('BACKGROUND', (0, 12), (1, 12), colors.lightgrey),
                ('FONTNAME', (0, 13), (0, 15), 'Helvetica'), 
            ]))
            elements.append(t)
            
            if idx < len(matching_logs) - 1:
                elements.append(PageBreak())

    else:
        # Summary mode
        filename = f"Combined_Summary_Report_{clean_sample}_{datetime_str}.pdf"
        elements.append(Paragraph(f"Combined Summary Test Report: {sample_code}", title_style))
        elements.append(Spacer(1, 20))
        
        base_log = matching_logs[0]
        common_data = [
            ["Sample Code:", sample_code],
            ["IS Code:", base_log.get('is_code', '3854:1997')],
            ["Sample Type:", base_log.get('sample_type', '')],
            ["Cross-Sectional Area:", base_log.get('area', '')],
            ["Bushing Hole Diameter:", base_log.get('diameter', '')],
            ["Rating:", base_log.get('rating', '')],
            ["Height:", base_log.get('height', '')],
            ["Weight:", base_log.get('weight', '')],
        ]
        ct = Table(common_data, colWidths=[200, 250])
        ct.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(ct)
        elements.append(Spacer(1, 40))
        
        summary_header = ["Test Instance", "Date", "Time", "Actual Duration", "Slip Out", "Cond. Break", "Cond. Damage", "Status"]
        summary_data = [summary_header]
        
        for idx, log_data in enumerate(matching_logs):
            time_str = log_data.get('time')
            date_val = "N/A"
            time_val = "N/A"
            if time_str:
                try:
                    dt = datetime.datetime.fromisoformat(time_str)
                    date_val = dt.strftime("%Y-%m-%d")
                    time_val = dt.strftime("%H:%M:%S")
                except: pass

            set_duration = log_data.get('duration', 0)
            set_dur_str = format_duration(set_duration)
            actual_dur_str = "N/A"
            if log_data.get('status') == 'Fail' and log_data.get('time') and log_data.get('end_time'):
                try:
                    st_dt = datetime.datetime.fromisoformat(log_data['time'])
                    en_dt = datetime.datetime.fromisoformat(log_data['end_time'])
                    actual_dur_str = format_duration(int((en_dt - st_dt).total_seconds()))
                except: pass
            elif log_data.get('status') == 'Pass':
                 actual_dur_str = set_dur_str

            st = log_data.get('status', 'N/A')
            fr = log_data.get('failure_reason', '')
            slip_out = "Fail" if fr == 'Weight Fallen Down!' else "Pass"
            c_break = log_data.get('conductor_break', 'N/A')
            c_damage = log_data.get('conductor_damage', 'N/A')
            fs = "Unsatisfactory" if st == 'Fail' else "Satisfactory"
            
            summary_data.append([
                f"#{idx+1}",
                date_val, time_val, actual_dur_str, slip_out, c_break, c_damage, fs
            ])
            
        st_table = Table(summary_data)
        st_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(st_table)

    doc.build(elements)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )


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
            time.sleep(1)
            oled_display.clear()
        
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
