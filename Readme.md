# Conductor Damage Testing Tool

Circuit Diagram
![circuit](/screenshots/circuit_image.png)

## Overview

This is a web-based application designed for conducting and monitoring conductor damage tests. It provides a user-friendly interface to start, stop, and monitor tests, record high-quality video evidence, and manage test history. The application is built with a Python Flask back-end and a responsive HTML/JavaScript front-end, making it a robust solution for laboratory or workshop environments.

## Key Features

- **Live Camera Feed:** Monitor tests in real-time with a live video stream directly in your browser.
- **Test Timer & Control:** Set a specific duration for each test, with the ability to start, stop, and reset tests from the UI.
- **Automated Video Recording:** Every test is automatically recorded and saved, ensuring a complete visual log.
- **Test History & Management:** A dedicated history page lists all previous tests, allowing you to review, delete, or download their data.
- **Data Packaging:** Download a complete package for any test, including the full video recording and a detailed log file, all bundled in a convenient `.zip` archive.
- **System Monitoring:** A real-time dashboard displays key system performance metrics, including CPU, memory, and disk usage.
- **Robust State Management:** The application is designed to handle browser navigation and page reloads gracefully. Timers and recordings continue to run on the server, and the UI automatically resynchronizes when you return to the page.

## Technology Stack

- **Back-End:** Python with the Flask micro-framework.
- **Video Processing:** OpenCV (`opencv-python-headless`) for camera handling and video recording.
- **System Metrics:** `psutil` for accessing system hardware and performance data.
- **Front-End:** Standard HTML5, CSS3, and modern JavaScript (ES6+).

## Project Structure

```
.
├── app.py              # Main Flask application entry point
├── devserver.sh        # Development server startup script
├── requirements.txt    # Python dependencies
├── src
│   ├── api.py          # All back-end API routes
│   ├── camera.py       # Camera management and recording logic
│   ├── index.html      # Home page for test control and live view
│   ├── history.html    # Test history and log management page
│   └── system-info.html # System monitoring dashboard
└── test_logs/          # Default directory for storing videos and logs
```

## Setup and Running the Project

To run the application in a local development environment, follow these steps:

1.  **Activate Virtual Environment:** It is recommended to use a virtual environment. If you are using the pre-configured Nix environment, this is already handled for you. To activate it, run:
    ```bash
    source .venv/bin/activate
    ```
    or
    ```
    source /home/pi/RaspberryPI-Camera-Automation/virt/bin/activate
    ```

2.  **Install Dependencies:** Install all the required Python packages.
    ```bash
    pip install -r requirements.txt
    ```
    Install required system libs (OpenCV's native library (libGL.so.1) is missing)
    ``` sudo apt update
    sudo apt install -y libgl1 libsm6 libxext6 libxrender1
    # if libgl1 isn't found, try:
    # sudo apt install -y libgl1-mesa-glx
    ```
3.  **Run the Server:** Start the Flask development server.
    ```bash
    ./devserver.sh
    ```
    Alternatively, you can run `python app.py`.

4.  **Access the Application:** Open your web browser and navigate to the local server address provided by Flask (typically `http://127.0.0.1:5000`).

## API Endpoints

The application exposes several API endpoints to control its functionality:

- `POST /api/test/start`: Starts a new test and initiates video recording.
- `POST /api/test/stop`: Stops the currently running test.
- `GET /api/test/status`: Retrieves the status of the active test.
- `GET /api/test/logs`: Fetches a list of all historical test logs.
- `DELETE /api/test/logs/<log_id>`: Deletes a specific test log and its associated video file.
- `GET /api/download/package/<log_id>`: Downloads a `.zip` archive containing the test video and log file.
- `GET /api/camera/feed`: Provides the live MJPEG video stream.
- `POST /api/camera/release`: Releases the front-end's reference to the camera, allowing it to turn off if not otherwise in use.
- `GET /api/stats`: Provides real-time system performance data.
## Autostart
```
sudo nano /etc/systemd/system/flaskcam.service
```
```
    [Unit]
    Description=Flask Camera Automation
    After=network.target

    [Service]
    User=pi
    WorkingDirectory=/home/pi/RaspberryPI-Camera-Automation
    ExecStart=/usr/bin/python3 /home/pi/RaspberryPI-Camera-Automation/app.py
    Restart=always

    [Install]
    WantedBy=multi-user.target
```
To start service
```
sudo systemctl enable flaskcam.service
sudo systemctl start flaskcam.service
```
check status
```
sudo systemctl status flaskcam.service
● flaskcam.service - Flask Camera Automation
     Loaded: loaded (/etc/systemd/system/flaskcam.service; enabled; preset: enabled)
     Active: active (running) since Tue 2025-10-28 11:51:50 IST; 25s ago
 Invocation: 7a13d34c8a5a46d99434c22cd140305e
   Main PID: 83072 (python3)
      Tasks: 7 (limit: 3918)
        CPU: 3.335s
     CGroup: /system.slice/flaskcam.service
             └─83072 /usr/bin/python3 /home/pi/RaspberryPI-Camera-Automation/app.py

Oct 28 11:51:52 raspberrypi python3[83072]: Initializing OLEDDisplay...
Oct 28 11:51:52 raspberrypi python3[83072]: OLED display initialized successfully.
Oct 28 11:51:52 raspberrypi python3[83072]: Error starting camera simulator: [Errno 2] No such file or directory: '/home/pi/RaspberryPI-Camera-Automation/.ve>
Oct 28 11:51:52 raspberrypi python3[83072]:  * Serving Flask app 'app'
Oct 28 11:51:52 raspberrypi python3[83072]:  * Debug mode: on
Oct 28 11:51:52 raspberrypi python3[83072]: WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server ins>
Oct 28 11:51:52 raspberrypi python3[83072]:  * Running on all addresses (0.0.0.0)
Oct 28 11:51:52 raspberrypi python3[83072]:  * Running on http://127.0.0.1:8080
Oct 28 11:51:52 raspberrypi python3[83072]:  * Running on http://192.168.1.175:8080
Oct 28 11:51:52 raspberrypi python3[83072]: Press CTRL+C to quit
```
Stopping once
```
sudo systemctl stop flaskcam.service

sudo systemctl status flaskcam.service
○ flaskcam.service - Flask Camera Automation
     Loaded: loaded (/etc/systemd/system/flaskcam.service; enabled; preset: enabled)
     Active: inactive (dead) since Tue 2025-10-28 11:54:51 IST; 6s ago
   Duration: 3min 1.274s
 Invocation: 7a13d34c8a5a46d99434c22cd140305e
    Process: 83072 ExecStart=/usr/bin/python3 /home/pi/RaspberryPI-Camera-Automation/app.py (code=killed, signal=TERM)
   Main PID: 83072 (code=killed, signal=TERM)
        CPU: 1min 1.669s

Oct 28 11:52:38 raspberrypi python3[83072]: [1:28:51.514483108] [83891]  INFO Camera camera_manager.cpp:220 Adding camera '/base/soc/i2c0mux/i2c@1/ov5647@36'>
Oct 28 11:52:38 raspberrypi python3[83072]: [1:28:51.514535052] [83891]  INFO RPI vc4.cpp:440 Registered camera /base/soc/i2c0mux/i2c@1/ov5647@36 to Unicam d>
Oct 28 11:52:38 raspberrypi python3[83072]: [1:28:51.514568218] [83891]  INFO RPI pipeline_base.cpp:1107 Using configuration file '/usr/share/libcamera/pipel>
Oct 28 11:52:38 raspberrypi python3[83072]: [1:28:51.522207872] [83883]  INFO Camera camera.cpp:1215 configuring streams: (0) 1920x1080-XBGR8888/Rec709/Rec70>
Oct 28 11:52:38 raspberrypi python3[83072]: [1:28:51.522653661] [83891]  INFO RPI vc4.cpp:615 Sensor: /base/soc/i2c0mux/i2c@1/ov5647@36 - Selected sensor for>
Oct 28 11:52:39 raspberrypi python3[83072]: 192.168.1.119 - - [28/Oct/2025 11:52:39] "GET /api/camera/feed HTTP/1.1" 200 -
Oct 28 11:54:51 raspberrypi systemd[1]: Stopping flaskcam.service - Flask Camera Automation...
Oct 28 11:54:51 raspberrypi systemd[1]: flaskcam.service: Deactivated successfully.
Oct 28 11:54:51 raspberrypi systemd[1]: Stopped flaskcam.service - Flask Camera Automation.
Oct 28 11:54:51 raspberrypi systemd[1]: flaskcam.service: Consumed 1min 1.669s CPU time.

```
Stopping autostart
```
sudo systemctl disable flaskcam.service
Removed '/etc/systemd/system/multi-user.target.wants/flaskcam.service'.
```
## Screenshots
![indexpage](/screenshots/index.png)
![SystemInfo](/screenshots/sys%20info.png)
![TestHistory](/screenshots/test%20history.png)

