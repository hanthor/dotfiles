#!/usr/bin/env python3
import os
import sys
import time
import glob
import subprocess
import logging
from pathlib import Path

# Setup logging
log_dir = Path.home() / ".local/share/system-mitigator"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "mitigator.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logging.info("System Mitigator Daemon started.")

# State variables
last_throttle_notification_time = 0
last_journal_notification_time = 0
throttle_seconds_accumulator = 0
last_journal_restarts = None

def get_pkg_temp():
    """Read Intel CPU package temperature from sysfs."""
    try:
        for path in glob.glob("/sys/class/thermal/thermal_zone*"):
            type_path = os.path.join(path, "type")
            temp_path = os.path.join(path, "temp")
            if os.path.exists(type_path) and os.path.exists(temp_path):
                with open(type_path, "r") as f:
                    tz_type = f.read().strip()
                if tz_type == "x86_pkg_temp":
                    with open(temp_path, "r") as f:
                        temp_raw = int(f.read().strip())
                    return temp_raw / 1000.0  # Convert millidegrees to degrees
    except Exception as e:
        logging.error(f"Error reading CPU temperature: {e}")
    return None

def check_cpu_throttling():
    """Check if all CPU cores are locked at minimum frequency (400 MHz)."""
    global throttle_seconds_accumulator, last_throttle_notification_time
    try:
        cur_freq_files = glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")
        min_freq_files = glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_min_freq")
        
        if not cur_freq_files:
            return
            
        cores_total = len(cur_freq_files)
        cores_at_min = 0
        
        for cur_file in cur_freq_files:
            min_file = cur_file.replace("scaling_cur_freq", "scaling_min_freq")
            if os.path.exists(min_file):
                with open(cur_file, "r") as f:
                    cur_freq = int(f.read().strip())
                with open(min_file, "r") as f:
                    min_freq = int(f.read().strip())
                
                # Check if core is running at or below the minimum scaling frequency (e.g. 400 MHz)
                # Allowing a tiny tolerance of 5% in case of scaling deviations
                if cur_freq <= min_freq * 1.05:
                    cores_at_min += 1
                    
        ratio_at_min = cores_at_min / cores_total
        
        # If more than 85% of cores are locked at minimum frequency
        if ratio_at_min >= 0.85:
            throttle_seconds_accumulator += 10
            logging.warning(f"CPU Throttling detected: {cores_at_min}/{cores_total} cores locked at minimum frequency. Accumulator: {throttle_seconds_accumulator}s")
            
            # If stuck in this state for 20 seconds, and package is cool, it's a false EC lock
            if throttle_seconds_accumulator >= 20:
                temp = get_pkg_temp()
                if temp is not None and temp < 65.0:
                    current_time = time.time()
                    # Rate limit notifications to once every 5 minutes
                    if current_time - last_throttle_notification_time > 300:
                        msg = (
                            f"All CPU cores are locked at 400 MHz (EC Fail-safe) but the CPU temperature is cool ({temp:.1f}°C).\n\n"
                            "Action Recommended:\n"
                            "1. Unplug and replug your USB-C charger.\n"
                            "2. Perform a 60-second power button reset (shut down, unplug power, hold power button for 60s)."
                        )
                        logging.critical("CRITICAL: CPU locked at 400 MHz with cool temperatures! Sending notification.")
                        send_notification("System Throttling Alert", msg, critical=True)
                        last_throttle_notification_time = current_time
        else:
            if throttle_seconds_accumulator > 0:
                logging.info(f"System recovered from throttling. Cores at min: {cores_at_min}/{cores_total}")
            throttle_seconds_accumulator = 0
            
    except Exception as e:
        logging.error(f"Error checking CPU throttling: {e}")

def get_journald_restarts():
    """Query systemd-journald restart count using systemctl show."""
    try:
        res = subprocess.run(
            ["systemctl", "show", "systemd-journald.service", "-p", "NRestarts"],
            capture_output=True, text=True, check=True
        )
        output = res.stdout.strip()
        if "NRestarts=" in output:
            restarts = int(output.split("=")[1])
            return restarts
    except Exception as e:
        logging.error(f"Error querying systemd-journald restarts: {e}")
    return None

def check_journald_health():
    """Detect if systemd-journald is in a crash loop by tracking NRestarts."""
    global last_journal_restarts, last_journal_notification_time
    restarts = get_journald_restarts()
    
    if restarts is not None:
        if last_journal_restarts is not None:
            diff = restarts - last_journal_restarts
            if diff > 0:
                logging.warning(f"systemd-journald restarted! Previous count: {last_journal_restarts}, Current count: {restarts} (diff: {diff})")
                
                # If it restarted more than twice in our polling interval (10 seconds), it's a tight crash loop
                if diff >= 2:
                    current_time = time.time()
                    if current_time - last_journal_notification_time > 300:
                        msg = (
                            "systemd-journald is crashing in a loop. This is usually caused by journal log file corruption "
                            "and can lead to complete desktop freezes and lockups.\n\n"
                            "Action Recommended:\n"
                            "Run 'sudo journalctl --vacuum-time=1s && sudo systemctl restart systemd-journald' to clear corrupted journals."
                        )
                        logging.critical("CRITICAL: systemd-journald crash loop detected! Sending notification.")
                        send_notification("System Service Crash Loop", msg, critical=True)
                        last_journal_notification_time = current_time
        
        last_journal_restarts = restarts

def send_notification(title, message, critical=False):
    """Send a desktop notification using notify-send."""
    try:
        urgency = "critical" if critical else "normal"
        icon = "dialog-warning" if critical else "dialog-information"
        subprocess.run([
            "notify-send",
            "-u", urgency,
            "-i", icon,
            "-a", "System Mitigator",
            title,
            message
        ], check=True)
    except Exception as e:
        logging.error(f"Failed to send desktop notification: {e}")

# Main loop
try:
    # Initialize restart count on start
    last_journal_restarts = get_journald_restarts()
    logging.info(f"Initial systemd-journald restarts count: {last_journal_restarts}")
    
    while True:
        check_cpu_throttling()
        check_journald_health()
        time.sleep(10)
except KeyboardInterrupt:
    logging.info("System Mitigator Daemon stopped manually.")
except Exception as e:
    logging.critical(f"Daemon crashed with uncaught exception: {e}")
