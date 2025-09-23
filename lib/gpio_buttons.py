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
        self.DEBOUNCE_TIME = 0.1  # Debounce delay in seconds
        self.SELECTION_TIMEOUT = 30  # Auto-exit program selection after N seconds

        # State management
        self.in_selection_mode = False  # True when in program selection mode
        self.last_selection_activity = 0  # Last time selection mode was used

        # Profile management
        profiles_dir = getattr(config, 'kiln_profiles_directory', 'storage/profiles')
        self.profile_manager = ProfileManager(profiles_dir)

        # Button state tracking (for debouncing)
        self.last_program_press = 0     # Last program button press time
        self.last_startstop_press = 0   # Last start/stop button press time

        self.init_buttons()

        # Delay to let TFT display thread start, then show default program
        threading.Timer(1.0, self.show_default_program).start()

    def show_default_program(self):
        """Show default program briefly as a message if configured and available"""
        if (hasattr(config, 'default_program') and config.default_program and
            self.profile_manager.get_profile_count() > 0):

            profile = self.profile_manager.get_current_profile()
            if profile and self.tft_display:
                log.info(f"Showing default program message: {profile['name']}")
                # Show as a temporary message instead of entering selection mode
                message = f"Default: {profile['name']}\nPress button to cycle"
                self.tft_display.show_message(message, 5)  # Show for 5 seconds

    def init_buttons(self):
        """Initialize GPIO buttons"""
        try:
            # Configure program cycle button
            self.program_button = digitalio.DigitalInOut(config.gpio_program_button)
            self.program_button.direction = digitalio.Direction.INPUT
            self.program_button.pull = digitalio.Pull.UP

            # Configure start/stop button
            self.startstop_button = digitalio.DigitalInOut(config.gpio_startstop_button)
            self.startstop_button.direction = digitalio.Direction.INPUT
            self.startstop_button.pull = digitalio.Pull.UP

            log.info("GPIO buttons initialized successfully")

        except Exception as e:
            log.error(f"Failed to initialize GPIO buttons: {e}")
            self.program_button = None
            self.startstop_button = None

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

    def is_button_pressed(self, button):
        """Check if button is pressed (accounting for pull-up resistor)"""
        if button is None:
            return False
        return not button.value  # Pressed = low with pull-up

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
        current_time = time.time()

        # Debounce check
        if current_time - self.last_program_press < self.DEBOUNCE_TIME:
            return

        self.last_program_press = current_time

        # Only work in IDLE state
        if self.oven.state != "IDLE":
            log.info("Program button ignored - kiln not in IDLE state")
            return

        # Enter or continue selection mode
        self.in_selection_mode = True
        self.last_selection_activity = current_time

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
        current_time = time.time()

        # Debounce check
        if current_time - self.last_startstop_press < self.DEBOUNCE_TIME:
            return

        self.last_startstop_press = current_time

        if self.oven.state == "IDLE":
            self.handle_start()
        elif self.oven.state in ["RUNNING", "PAUSED"]:
            self.handle_stop()

    def handle_start(self):
        """Handle start button in IDLE state"""
        if not self.in_selection_mode:
            log.info("Start button pressed but no program selected")
            if self.tft_display:
                self.tft_display.show_message("No program selected", 3)
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
            # Exit selection mode if active
            self.in_selection_mode = False
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

        while self.running:
            try:
                # Check program button
                if self.is_button_pressed(self.program_button):
                    self.handle_program_button()

                # Check start/stop button
                if self.is_button_pressed(self.startstop_button):
                    self.handle_startstop_button()

                # Check selection timeout
                self.check_selection_timeout()

                # Small delay to prevent excessive CPU usage
                time.sleep(0.1)

            except Exception as e:
                log.error(f"Error in button manager loop: {e}")
                time.sleep(1)  # Wait longer on error

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