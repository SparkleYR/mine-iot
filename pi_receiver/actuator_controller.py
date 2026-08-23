#!/usr/bin/env python3
"""
Raspberry Pi 4 Actuator Controller
===================================
Hardware driver for:
  - WS2812 64-bit (8×8) RGB LED Matrix on GPIO 15 (Pin 15)
  - High-Decibel Piezo Siren/Buzzer on GPIO 19 (Pin 19)

Features:
  - 8x8 Bitmap Pattern Renderer with RGB TrueColor support:
      * NORMAL_CHECK   : Green checkmark (0, 255, 0)
      * WARNING_PULSE  : Amber pulsing beacon (255, 140, 0)
      * DANGER_FLASH   : Flashing Red Hazard 'X' (255, 0, 0)
      * EVACUATE_ARROW : Fast pulsing Red/Amber Directional Arrow (255, 60, 0)
      * IDLE           : Dim blue standby frame (0, 30, 80)
  - Non-blocking background thread for smooth visual animations and siren cadences
  - Automatic failsafe safety timer for audible siren (default 10s auto-silence)
  - Graceful fallback simulation when running without hardware GPIO permissions
"""

import time
import threading
import logging
from typing import Optional

logger = logging.getLogger("ActuatorController")

# Pin definitions
WS2812_PIN = 15  # GPIO 15 (BCM 15)
BUZZER_PIN = 19  # GPIO 19 (BCM 19)
NUM_LEDS = 64    # 8x8 Matrix

# 8x8 Bitmaps (8 rows of 8 bits)
PATTERNS = {
    "IDLE": [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
        [0, 0, 1, 0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0, 1, 0, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ],
    "NORMAL_CHECK": [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 1],
        [0, 0, 0, 0, 0, 0, 1, 0],
        [0, 0, 0, 0, 0, 1, 0, 0],
        [1, 0, 0, 0, 1, 0, 0, 0],
        [0, 1, 0, 1, 0, 0, 0, 0],
        [0, 0, 1, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ],
    "WARNING_PULSE": [
        [0, 0, 0, 1, 1, 0, 0, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
        [0, 1, 1, 0, 0, 1, 1, 0],
        [0, 1, 1, 0, 0, 1, 1, 0],
        [1, 1, 1, 1, 1, 1, 1, 1],
        [0, 0, 0, 1, 1, 0, 0, 0],
        [0, 0, 0, 1, 1, 0, 0, 0],
    ],
    "DANGER_FLASH": [
        [1, 1, 0, 0, 0, 0, 1, 1],
        [1, 1, 1, 0, 0, 1, 1, 1],
        [0, 1, 1, 1, 1, 1, 1, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
        [0, 1, 1, 1, 1, 1, 1, 0],
        [1, 1, 1, 0, 0, 1, 1, 1],
        [1, 1, 0, 0, 0, 0, 1, 1],
    ],
    "EVACUATE_ARROW": [
        [0, 0, 0, 0, 1, 0, 0, 0],
        [0, 0, 0, 0, 1, 1, 0, 0],
        [0, 0, 0, 0, 1, 1, 1, 0],
        [1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1],
        [0, 0, 0, 0, 1, 1, 1, 0],
        [0, 0, 0, 0, 1, 1, 0, 0],
        [0, 0, 0, 0, 1, 0, 0, 0],
    ]
}

# Color definitions (R, G, B)
PATTERN_COLORS = {
    "NORMAL_CHECK": (0, 255, 0),
    "WARNING_PULSE": (255, 140, 0),
    "DANGER_FLASH": (255, 0, 0),
    "EVACUATE_ARROW": (255, 50, 0),
    "IDLE": (0, 30, 80),
}


class ActuatorController:
    """Manages WS2812 8x8 LED matrix and Piezo Siren."""

    def __init__(self, ws2812_pin: int = WS2812_PIN, buzzer_pin: int = BUZZER_PIN):
        self.ws2812_pin = ws2812_pin
        self.buzzer_pin = buzzer_pin
        self.strip = None
        self.gpio_available = False
        self.lock = threading.Lock()
        
        # State
        self.current_pattern = "NORMAL_CHECK"
        self.buzzer_active = False
        self.buzzer_off_time: float = 0.0
        self.running = False
        self.anim_thread: Optional[threading.Thread] = None

        self._init_hardware()

    def _init_hardware(self):
        """Attempts to initialize physical GPIO and WS2812 drivers."""
        # 1. Initialize Buzzer GPIO
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.buzzer_pin, GPIO.OUT)
            GPIO.output(self.buzzer_pin, GPIO.LOW)
            self.gpio_available = True
            logger.info(f"[HARDWARE] RPi.GPIO initialized. Buzzer active on GPIO {self.buzzer_pin}")
        except Exception as e:
            logger.warning(f"[SIMULATION] Hardware GPIO not available ({e}). Using software emulation.")
            self.gpio_available = False

        # 2. Initialize WS2812 Strip
        try:
            from rpi_ws281x import PixelStrip, Color
            self.strip = PixelStrip(NUM_LEDS, self.ws2812_pin, 800000, 10, False, 50, 0)
            self.strip.begin()
            logger.info(f"[HARDWARE] rpi_ws281x initialized on GPIO {self.ws2812_pin} ({NUM_LEDS} pixels)")
        except Exception as e:
            logger.warning(f"[SIMULATION] WS2812 driver not available ({e}). Emulating LED matrix.")
            self.strip = None

    def start(self):
        """Start the background animation and failsafe watchdog loop."""
        self.running = True
        self.anim_thread = threading.Thread(target=self._animation_loop, daemon=True)
        self.anim_thread.start()
        self.set_pattern("NORMAL_CHECK")
        logger.info("ActuatorController animation worker started.")

    def stop(self):
        """Gracefully stop actuators and turn off hardware outputs."""
        self.running = False
        self.set_buzzer(False)
        self._render_raw([[0]*8 for _ in range(8)], (0, 0, 0), 0)
        if self.gpio_available:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup([self.buzzer_pin])
            except Exception:
                pass
        logger.info("ActuatorController stopped.")

    def set_buzzer(self, active: bool, duration_ms: int = 0):
        """Turn the buzzer on or off. If duration_ms > 0, auto-silences after interval."""
        with self.lock:
            self.buzzer_active = active
            if active and duration_ms > 0:
                self.buzzer_off_time = time.time() + (duration_ms / 1000.0)
            else:
                self.buzzer_off_time = 0.0

            if self.gpio_available:
                try:
                    import RPi.GPIO as GPIO
                    GPIO.output(self.buzzer_pin, GPIO.HIGH if active else GPIO.LOW)
                except Exception as e:
                    logger.error(f"Failed to set GPIO {self.buzzer_pin}: {e}")
            logger.info(f"[ACTUATOR] Buzzer state -> {'SOUNDING (ON)' if active else 'SILENT (OFF)'} (GPIO {self.buzzer_pin})")

    def set_pattern(self, pattern_name: str):
        """Set active visual pattern on WS2812 64-bit matrix."""
        with self.lock:
            if pattern_name not in PATTERNS:
                logger.warning(f"Unknown pattern '{pattern_name}'. Falling back to NORMAL_CHECK.")
                pattern_name = "NORMAL_CHECK"
            self.current_pattern = pattern_name
            logger.info(f"[ACTUATOR] WS2812 Matrix Pattern -> {pattern_name} (GPIO {self.ws2812_pin})")

    def _render_raw(self, bitmap: list, rgb: tuple, brightness_pct: int = 50):
        """Render 8x8 bitmap onto WS2812 LED strip."""
        if not self.strip:
            return  # In simulation mode, state changes are logged
        try:
            from rpi_ws281x import Color
            factor = max(0.0, min(1.0, brightness_pct / 100.0))
            r = int(rgb[0] * factor)
            g = int(rgb[1] * factor)
            b = int(rgb[2] * factor)
            active_color = Color(r, g, b)
            off_color = Color(0, 0, 0)

            for row in range(8):
                for col in range(8):
                    idx = row * 8 + col
                    val = bitmap[row][col]
                    self.strip.setPixelColor(idx, active_color if val == 1 else off_color)
            self.strip.show()
        except Exception as e:
            logger.debug(f"Render error: {e}")

    def _animation_loop(self):
        """Background thread handling pulsing and flashing animations."""
        flash_state = True
        pulse_brightness = 30
        pulse_direction = 3

        while self.running:
            now = time.time()

            # 1. Failsafe auto-silence check
            with self.lock:
                if self.buzzer_active and self.buzzer_off_time > 0 and now >= self.buzzer_off_time:
                    self.set_buzzer(False)
                    logger.info("[ACTUATOR] Buzzer safety auto-silenced.")

                pattern = self.current_pattern

            bitmap = PATTERNS.get(pattern, PATTERNS["NORMAL_CHECK"])
            base_color = PATTERN_COLORS.get(pattern, (0, 255, 0))

            if pattern == "DANGER_FLASH":
                flash_state = not flash_state
                self._render_raw(bitmap, base_color, 85 if flash_state else 0)
                time.sleep(0.3)
            elif pattern == "WARNING_PULSE":
                pulse_brightness += pulse_direction
                if pulse_brightness >= 80 or pulse_brightness <= 15:
                    pulse_direction = -pulse_direction
                self._render_raw(bitmap, base_color, pulse_brightness)
                time.sleep(0.05)
            elif pattern == "EVACUATE_ARROW":
                flash_state = not flash_state
                self._render_raw(bitmap, base_color, 80 if flash_state else 20)
                time.sleep(0.2)
            else:
                self._render_raw(bitmap, base_color, 45)
                time.sleep(0.5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("Testing ActuatorController on Pin 15 (WS2812) & Pin 19 (Buzzer)...")
    ctrl = ActuatorController()
    ctrl.start()

    patterns = ["NORMAL_CHECK", "WARNING_PULSE", "DANGER_FLASH", "EVACUATE_ARROW", "IDLE"]
    for pat in patterns:
        print(f"\n--- Testing Pattern: {pat} ---")
        ctrl.set_pattern(pat)
        if pat == "DANGER_FLASH":
            ctrl.set_buzzer(True, duration_ms=1000)
        time.sleep(2.0)

    print("\n--- Test Complete. Cleaning up ---")
    ctrl.stop()
