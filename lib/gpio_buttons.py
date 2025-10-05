#!/usr/bin/env python

"""
GPIO Button Control for Kiln Controller

Provides physical button interface for:
- Program cycle button: cycles through available firing profiles (IDLE only)
- Start/stop button: starts selected program or stops running program
"""

import threading
import time
import logging
import json
import os
import requests
import digitalio
import config
from adafruit_debouncer import Debouncer
from watchdog import update_watchdog, register_thread, unregister_thread

log = logging.getLogger(__name__)

class ProfileManager:
    """Manages loading and cycling through kiln firing profiles"""

    def __init__(self, profiles_directory):
        self.profiles_directory = profiles_directory
        self.profiles = []
        self.current_index = 0
        self.load_profiles()
        self.set_default_profile()

    def load_profiles(self):
        """Load all available profiles from storage directory"""
        try:
            profile_files = os.listdir(self.profiles_directory)
            profile_files = [f for f in profile_files if f.endswith('.json')]
            profile_files.sort()  # Alphabetical order

            self.profiles = []
            for filename in profile_files:
                try:
                    filepath = os.path.join(self.profiles_directory, filename)
                    with open(filepath, 'r') as f:
                        profile_data = json.load(f)

                    # Extract key information
                    profile_info = {
                        'name': profile_data.get('name', filename.replace('.json', '')),
                        'filename': filename,
                        'data': profile_data.get('data', []),
                        'max_temp': self._get_max_temperature(profile_data.get('data', [])),
                        'duration': self._get_duration(profile_data.get('data', []))
                    }
                    self.profiles.append(profile_info)

                except Exception as e:
                    log.warning(f"Failed to load profile {filename}: {e}")

            log.info(f"Loaded {len(self.profiles)} firing profiles")

        except Exception as e:
            log.error(f"Failed to load profiles directory: {e}")
            self.profiles = []

    def set_default_profile(self):
        """Set the current index to the default program if specified in config"""
        if hasattr(config, 'default_program') and config.default_program:
            # Look for profile matching the default program name
            for i, profile in enumerate(self.profiles):
                profile_name = profile['filename'].replace('.json', '')
                if profile_name == config.default_program:
                    self.current_index = i
                    log.info(f"Set default program to: {profile['name']} (index {i})")
                    return

            # Also try matching the display name
            for i, profile in enumerate(self.profiles):
                if profile['name'] == config.default_program:
                    self.current_index = i
                    log.info(f"Set default program to: {profile['name']} (index {i})")
                    return

            log.warning(f"Default program '{config.default_program}' not found in available profiles")

    def _get_max_temperature(self, data):
        """Extract maximum temperature from profile data"""
        if not data:
            return 0
        return max(point[1] for point in data)

    def _get_duration(self, data):
        """Extract total duration from profile data in hours"""
        if not data:
            return 0
        return data[-1][0] / 3600.0  # Convert seconds to hours

    def get_current_profile(self):
        """Get currently selected profile"""
        if not self.profiles:
            return None
        return self.profiles[self.current_index]

    def cycle_to_next(self):
        """Cycle to next profile"""
        if not self.profiles:
            return None
        self.current_index = (self.current_index + 1) % len(self.profiles)
        return self.get_current_profile()

    def get_profile_count(self):
        """Get total number of profiles"""
        return len(self.profiles)

class ButtonManager(threading.Thread):
    """Manages GPIO button inputs for kiln control"""

    def __init__(self, oven, tft_display=None):
        threading.Thread.__init__(self)
        self.daemon = True  # Thread dies when main program exits
        self.oven = oven    # Keep reference for state checking
        self.tft_display = tft_display  # Optional TFT display for feedback
        self.running = False  # Thread control flag

        # API configuration
        self.api_url = f"http://localhost:{config.listening_port}/api"

        # Button timing constants
        self.SELECTION_TIMEOUT = 30  # Auto-exit program selection after N seconds

        # State management
        self.in_selection_mode = False  # True when in program selection mode
        self.last_selection_activity = 0  # Last time selection mode was used

        # Profile management
        profiles_dir = getattr(config, 'kiln_profiles_directory', 'storage/profiles')
        self.profile_manager = ProfileManager(profiles_dir)

        self.init_buttons()

        # Delay to let TFT display thread start, then show default program
        threading.Timer(1.0, self.show_default_program).start()

    def show_default_program(self):
        """Show default program briefly as a message if configured and available"""
        if (hasattr(config, 'default_program') and config.default_program and
            self.profile_manager.get_profile_count() > 0):

            profile = self.profile_manager.get_current_profile()
            if profile:
                log.info(f"Setting default program: {profile['name']}")
                # Enter selection mode so the start button works
                self.in_selection_mode = True
                self.last_selection_activity = time.time()

                if self.tft_display:
                    # Show as a temporary message for 5 seconds, then show normal temp display
                    # Don't clear selection mode so start button continues to work
                    message = f"Default: {profile['name']}\nReady to start"
                    self.tft_display.show_message(message, 5, clear_selection=False)

    def init_buttons(self):
        """Initialize GPIO buttons with debouncing"""
        try:
            # Configure program cycle button
            program_pin = digitalio.DigitalInOut(config.gpio_program_button)
            program_pin.direction = digitalio.Direction.INPUT
            program_pin.pull = digitalio.Pull.UP
            self.program_button = Debouncer(program_pin)

            # Configure start/stop button
            startstop_pin = digitalio.DigitalInOut(config.gpio_startstop_button)
            startstop_pin.direction = digitalio.Direction.INPUT
            startstop_pin.pull = digitalio.Pull.UP
            self.startstop_button = Debouncer(startstop_pin)

            # Configure second start/stop button (GPIO20)
            if hasattr(config, 'gpio_startstop_button2'):
                startstop_pin2 = digitalio.DigitalInOut(config.gpio_startstop_button2)
                startstop_pin2.direction = digitalio.Direction.INPUT
                startstop_pin2.pull = digitalio.Pull.UP
                self.startstop_button2 = Debouncer(startstop_pin2)
                log.info("GPIO buttons initialized (including second start/stop on GPIO20)")
            else:
                self.startstop_button2 = None
                log.info("GPIO buttons initialized successfully with debouncing")

        except Exception as e:
            log.error(f"Failed to initialize GPIO buttons: {e}")
            self.program_button = None
            self.startstop_button = None
            self.startstop_button2 = None

    def start_button_manager(self):
        """Start the button monitoring thread"""
        if self.program_button and self.startstop_button:
            self.running = True
            self.start()
            log.info("Button manager started")
        else:
            log.error("Cannot start button manager - initialization failed")

    def stop_button_manager(self):
        """Stop the button monitoring thread"""
        self.running = False
        log.info("Button manager stopped")

    def update_buttons(self):
        """Update debouncer state - samples pins and tracks values over time.
        Must be called regularly for .fell and .rose properties to work.
        Default debounce interval is 10ms - input must be stable that long."""
        if self.program_button:
            self.program_button.update()
        if self.startstop_button:
            self.startstop_button.update()
        if self.startstop_button2:
            self.startstop_button2.update()

    def send_api_command(self, command, **kwargs):
        """Send command to kiln controller API"""
        try:
            payload = {"cmd": command}
            payload.update(kwargs)

            response = requests.post(
                self.api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    log.info(f"API command '{command}' successful")
                    return True
                else:
                    log.error(f"API command '{command}' failed: {result.get('error', 'Unknown error')}")
            else:
                log.error(f"API command '{command}' failed with status {response.status_code}")

        except Exception as e:
            log.error(f"Failed to send API command '{command}': {e}")

        return False

    def handle_program_button(self):
        """Handle program cycle button press"""
        # Only work in IDLE state
        if self.oven.state != "IDLE":
            log.info("Program button ignored - kiln not in IDLE state")
            return

        # Enter or continue selection mode
        self.in_selection_mode = True
        self.last_selection_activity = time.time()

        # Cycle to next profile
        profile = self.profile_manager.cycle_to_next()
        if profile:
            log.info(f"Selected profile: {profile['name']}")
            # Update display if available
            if self.tft_display:
                self.tft_display.set_selection_mode(profile)
        else:
            log.warning("No profiles available")

    def handle_startstop_button(self):
        """Handle start/stop button press"""
        if self.oven.state == "IDLE":
            self.handle_start()
        elif self.oven.state in ["RUNNING", "PAUSED"]:
            self.handle_stop()

    def handle_start(self):
        """Handle start button in IDLE state"""
        if not self.in_selection_mode:
            log.info("Start button pressed but no program selected")
            if self.tft_display:
                self.tft_display.show_message("No program", 3)
            return

        profile = self.profile_manager.get_current_profile()
        if not profile:
            log.warning("Start button pressed but no valid profile")
            return

        # Use API to start the kiln run
        success = self.send_api_command("run", profile=profile['name'])

        if success:
            log.info(f"Started kiln with profile: {profile['name']}")
            # Exit selection mode
            self.in_selection_mode = False
            if self.tft_display:
                self.tft_display.exit_selection_mode()
        else:
            log.error(f"Failed to start profile {profile['name']}")

    def handle_stop(self):
        """Handle stop button in RUNNING/PAUSED state"""
        log.info("Stop button pressed - stopping kiln run")

        success = self.send_api_command("stop")

        if success:
            # Keep the current program selected internally for easy restart
            # but show normal status display instead of selection screen
            current_profile = self.profile_manager.get_current_profile()
            if current_profile:
                log.info(f"Maintaining program selection internally: {current_profile['name']}")
                self.in_selection_mode = True
                self.last_selection_activity = time.time()
            else:
                self.in_selection_mode = False

            # Always show normal status display after stopping
            if self.tft_display:
                self.tft_display.exit_selection_mode()

    def check_selection_timeout(self):
        """Check if selection mode should timeout"""
        if not self.in_selection_mode:
            return

        current_time = time.time()
        if current_time - self.last_selection_activity > self.SELECTION_TIMEOUT:
            log.info("Program selection timeout - returning to normal display")
            self.in_selection_mode = False
            if self.tft_display:
                self.tft_display.exit_selection_mode()

    def run(self):
        """Main button monitoring loop"""
        log.info("Button manager thread started")

        # Register with watchdog
        register_thread("ButtonManager", "GPIO button monitoring thread")

        while self.running:
            try:
                # Update watchdog timestamp
                update_watchdog("ButtonManager")

                # Update button debouncers
                self.update_buttons()

                # Check for button press events (fell = pressed with pull-up)
                if self.program_button and self.program_button.fell:
                    self.handle_program_button()

                if self.startstop_button and self.startstop_button.fell:
                    self.handle_startstop_button()

                if self.startstop_button2 and self.startstop_button2.fell:
                    self.handle_startstop_button()

                # Check selection timeout
                self.check_selection_timeout()

                # Small delay to prevent excessive CPU usage
                time.sleep(0.1)

            except Exception as e:
                log.error(f"Error in button manager loop: {e}")
                time.sleep(1)  # Wait longer on error

        # Unregister from watchdog
        unregister_thread("ButtonManager")
        log.info("Button manager thread stopped")

def create_button_manager(oven, tft_display=None):
    """Create button manager if enabled in config"""
    if hasattr(config, 'enable_gpio_buttons') and config.enable_gpio_buttons:
        try:
            return ButtonManager(oven, tft_display)
        except Exception as e:
            log.error(f"Failed to create button manager: {e}")
            return None
    return None