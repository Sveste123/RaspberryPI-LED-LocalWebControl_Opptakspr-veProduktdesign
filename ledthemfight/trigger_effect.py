import requests
import json
import time
import threading
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[logging.FileHandler('/home/sverrestenbaek/ledthemfight/trigger_effect.log')]
)
logger = logging.getLogger('trigger_effect')

# URLs
BUTTON_URL = "http://bestemorssppelskur.local/button"
DISTANCE_URL = "http://bestemorssppelskur.local:5000/distance"

# Hardcoded settings
THRESHOLD_CM = 50.0  # Trigger if distance < 100 cm
EFFECT_NAME = "Warm_White"  # Effect to trigger
POLL_INTERVAL = 0.22  # Poll distance "Fetch distance" (in seconds)
EFFECT_DURATION = 60  # 60 seconds
RETRY_COUNT = 3  # Number of POST retries for stop

current_timer = None
effect_running = False

def trigger_effect(effect_name):
    """Send POST /button to trigger an effect."""
    payload = {"name": "effect", "value": effect_name}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(BUTTON_URL, data=json.dumps(payload), headers=headers, timeout=5)
        if response.status_code == 200:
            logger.info(f"Successfully triggered effect: {effect_name}")
            return True
        else:
            logger.error(f"Failed to trigger effect: {effect_name}, status: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Error sending POST /button for trigger: {e}")
        return False

def stop_effect():
    """Send POST /button to stop the current effect, retrying to ensure LEDs clear."""
    global effect_running, current_timer
    payload = {"name": "stop", "value": None}
    headers = {"Content-Type": "application/json"}
    success = False
    for attempt in range(RETRY_COUNT):
        try:
            response = requests.post(BUTTON_URL, data=json.dumps(payload), headers=headers, timeout=5)
            if response.status_code == 200:
                logger.info(f"Successfully stopped effect (attempt {attempt + 1})")
                success = True
            else:
                logger.error(f"Failed to stop effect, status: {response.status_code} (attempt {attempt + 1})")
        except Exception as e:
            logger.error(f"Error sending POST /button for stop: {e} (attempt {attempt + 1})")
        time.sleep(0.1)  # Short delay between retries
    if success:
        effect_running = False
        current_timer = None
        return True
    return False

def start_effect_timer():
    """Start a timer to stop the effect after EFFECT_DURATION expires."""
    global current_timer
    if current_timer:
        current_timer.cancel()
    current_timer = threading.Timer(EFFECT_DURATION, stop_effect)
    current_timer.start()

def poll_distance():
    """Fetch distance from sensor."""
    try:
        response = requests.get(DISTANCE_URL, timeout=5)
        if response.status_code == 200:
            distance = float(response.text.strip())
            logger.info(f"Fetched distance: {distance} cm")
            return distance
        else:
            logger.error(f"Failed to fetch distance, status: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error fetching distance: {e}")
        return None

if __name__ == "__main__":
    logger.info("Trigger effect script started")
    while True:
        if not effect_running:
            distance = poll_distance()
            if distance is not None and distance < THRESHOLD_CM:
                if trigger_effect(EFFECT_NAME):
                    effect_running = True
                    start_effect_timer()
                    logger.info(f"Started {EFFECT_NAME} for {EFFECT_DURATION} seconds")
        time.sleep(POLL_INTERVAL)
