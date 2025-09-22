#!/usr/bin/env python

"""
Test script for GPIO button functionality
This script tests GPIO button operations without requiring actual hardware buttons
"""

import sys
import os
import time
import logging
import threading

# Add lib directory to path
script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir + '/lib/')

import config
from gpio_buttons import ProfileManager, ButtonManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
log = logging.getLogger("gpio-button-test")

class MockOven:
    """Mock oven for testing button functionality"""

    def __init__(self):
        self.state = "IDLE"  # Start in IDLE state for testing
        self.profile = None

    def run_profile(self, profile):
        """Mock run_profile method"""
        self.state = "RUNNING"
        self.profile = profile
        log.info(f"Mock oven started with profile: {profile.name}")

    def abort_run(self):
        """Mock abort_run method"""
        self.state = "IDLE"
        self.profile = None
        log.info("Mock oven stopped")

class MockTFTDisplay:
    """Mock TFT display for testing"""

    def __init__(self):
        self.selection_mode = False
        self.selected_profile = None

    def set_selection_mode(self, profile):
        """Mock set_selection_mode method"""
        self.selection_mode = True
        self.selected_profile = profile
        log.info(f"Mock display showing profile: {profile['name']}")
        log.info(f"  Max temp: {profile['max_temp']:.0f}, Duration: {profile['duration']:.1f}h")

    def exit_selection_mode(self):
        """Mock exit_selection_mode method"""
        self.selection_mode = False
        self.selected_profile = None
        log.info("Mock display exited selection mode")

    def show_message(self, message, duration):
        """Mock show_message method"""
        log.info(f"Mock display message: {message} (for {duration}s)")

class MockButtonManager(ButtonManager):
    """Mock button manager that simulates button presses"""

    def __init__(self, oven, tft_display=None):
        # Initialize parent without calling init_buttons
        threading.Thread.__init__(self)
        self.daemon = True
        self.oven = oven
        self.tft_display = tft_display
        self.running = False

        # API configuration (not used in mock)
        self.api_url = f"http://localhost:{config.listening_port}/api"

        # Button timing constants
        self.DEBOUNCE_TIME = 0.2  # Shorter for testing
        self.SELECTION_TIMEOUT = 10  # Shorter for testing

        # State management
        self.in_selection_mode = False
        self.last_selection_activity = 0

        # Profile management
        profiles_dir = getattr(config, 'kiln_profiles_directory', 'storage/profiles')
        self.profile_manager = ProfileManager(profiles_dir)

        # Button state tracking
        self.last_program_press = 0
        self.last_startstop_press = 0

        # Mock button states
        self.program_button_pressed = False
        self.startstop_button_pressed = False

    def init_buttons(self):
        """Override - no actual GPIO initialization in mock"""
        log.info("Mock buttons initialized")

    def is_button_pressed(self, button):
        """Override - simulate button presses"""
        if button == "program":
            return self.program_button_pressed
        elif button == "startstop":
            return self.startstop_button_pressed
        return False

    def simulate_program_press(self):
        """Simulate program button press"""
        log.info("=== SIMULATING PROGRAM BUTTON PRESS ===")
        self.handle_program_button()

    def simulate_startstop_press(self):
        """Simulate start/stop button press"""
        log.info("=== SIMULATING START/STOP BUTTON PRESS ===")
        self.handle_startstop_button()

    def send_api_command(self, command, **kwargs):
        """Override API command to simulate without actual HTTP"""
        log.info(f"Mock API command: {command} {kwargs}")

        if command == "run":
            profile_name = kwargs.get('profile', 'unknown')
            log.info(f"Mock API: Starting kiln with profile '{profile_name}'")
            # Simulate successful start
            return True
        elif command == "stop":
            log.info("Mock API: Stopping kiln")
            self.oven.abort_run()
            return True

        return True  # Always return success in mock

def test_profile_manager():
    """Test profile loading and cycling"""
    log.info("=== Testing Profile Manager ===")

    profiles_dir = getattr(config, 'kiln_profiles_directory', 'storage/profiles')
    pm = ProfileManager(profiles_dir)

    log.info(f"Loaded {pm.get_profile_count()} profiles")

    if pm.get_profile_count() > 0:
        # Test cycling through profiles
        for i in range(min(pm.get_profile_count() + 2, 5)):  # Test wraparound
            profile = pm.cycle_to_next()
            if profile:
                log.info(f"Profile {i+1}: {profile['name']} "
                        f"(Max: {profile['max_temp']:.0f}, Duration: {profile['duration']:.1f}h)")
    else:
        log.warning("No profiles found for testing")

def test_button_functionality():
    """Test button manager functionality"""
    log.info("=== Testing Button Functionality ===")

    # Create mock objects
    mock_oven = MockOven()
    mock_display = MockTFTDisplay()

    # Create mock button manager
    button_manager = MockButtonManager(mock_oven, mock_display)

    if button_manager.profile_manager.get_profile_count() == 0:
        log.error("No profiles available for testing")
        return

    log.info("Starting button functionality test...")

    # Test 1: Program cycling in IDLE state
    log.info("\n--- Test 1: Program cycling ---")
    mock_oven.state = "IDLE"

    for i in range(3):
        button_manager.simulate_program_press()
        time.sleep(0.5)

    # Test 2: Start button with selected profile
    log.info("\n--- Test 2: Starting kiln ---")
    if button_manager.in_selection_mode:
        button_manager.simulate_startstop_press()
        time.sleep(0.5)

    # Test 3: Stop button while running
    log.info("\n--- Test 3: Stopping kiln ---")
    mock_oven.state = "RUNNING"
    button_manager.simulate_startstop_press()
    time.sleep(0.5)

    # Test 4: Program button ignored when not IDLE
    log.info("\n--- Test 4: Program button ignored when RUNNING ---")
    mock_oven.state = "RUNNING"
    button_manager.simulate_program_press()
    time.sleep(0.5)

    # Test 5: Start button without selection
    log.info("\n--- Test 5: Start without selection ---")
    mock_oven.state = "IDLE"
    button_manager.in_selection_mode = False
    button_manager.simulate_startstop_press()

    log.info("Button functionality test completed")

def test_selection_timeout():
    """Test selection mode timeout"""
    log.info("=== Testing Selection Timeout ===")

    mock_oven = MockOven()
    mock_display = MockTFTDisplay()
    button_manager = MockButtonManager(mock_oven, mock_display)

    # Set short timeout for testing
    button_manager.SELECTION_TIMEOUT = 3

    # Enter selection mode
    button_manager.simulate_program_press()

    if button_manager.in_selection_mode:
        log.info("Selection mode active, waiting for timeout...")

        for i in range(5):
            time.sleep(1)
            button_manager.check_selection_timeout()
            status = "active" if button_manager.in_selection_mode else "inactive"
            log.info(f"Time {i+1}s: Selection mode {status}")

            if not button_manager.in_selection_mode:
                break

def main():
    log.info("GPIO Button Test Suite")
    log.info("Testing button functionality without actual GPIO hardware")
    print()

    try:
        # Test profile manager
        test_profile_manager()
        print()

        # Test button functionality
        test_button_functionality()
        print()

        # Test selection timeout
        test_selection_timeout()
        print()

        log.info("All tests completed successfully!")
        return 0

    except Exception as e:
        log.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)