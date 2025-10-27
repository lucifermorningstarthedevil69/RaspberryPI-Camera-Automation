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

## Screenshots
![indexpage](/screenshots/index.png)
![SystemInfo](/screenshots/sys%20info.png)
![TestHistory](/screenshots/test%20history.png)
