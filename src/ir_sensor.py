import RPi.GPIO as GPIO
import time
import threading

class IRSensorMonitor:
    def __init__(self, sensor_pin, inactivity_timeout=8):
        self.sensor_pin = sensor_pin
        self.inactivity_timeout = inactivity_timeout
        self.last_state = None
        self.last_state_change_time = None
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.callback = None
        self.callback_fired = False

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.sensor_pin, GPIO.IN)

    def start_monitoring(self, callback):
        """Starts the sensor monitoring in a separate thread."""
        self.last_state = None
        self.last_state_change_time = time.time()
        self.stop_event.clear()
        self.callback_fired = False
        self.callback = callback
        self.monitor_thread = threading.Thread(target=self._monitor)
        self.monitor_thread.start()
        print(f"IR sensor monitoring started on pin {self.sensor_pin}")

    def stop_monitoring(self):
        """Stops the sensor monitoring thread."""
        self.stop_event.set()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join()
        print("IR sensor monitoring stopped.")

    def _monitor(self):
        """The internal method that runs in a loop to check the sensor."""
        while not self.stop_event.is_set():
            current_state = GPIO.input(self.sensor_pin)
            if self.last_state is None:
                self.last_state = current_state

            if current_state != self.last_state:
                self.last_state = current_state
                self.last_state_change_time = time.time()
            else:
                if not self.callback_fired and (time.time() - self.last_state_change_time > self.inactivity_timeout):
                    print(f"Sensor has been in state {self.last_state} for {self.inactivity_timeout} seconds. Firing callback.")
                    self.callback_fired = True
                    if self.callback:
                        # Use a thread to call the callback to avoid blocking
                        threading.Thread(target=self.callback).start()
            time.sleep(0.1)  # Check the sensor state every 100ms

    def cleanup(self):
        """Clean up GPIO resources."""
        print("Cleaning up GPIO pin.")
        GPIO.cleanup(self.sensor_pin)
