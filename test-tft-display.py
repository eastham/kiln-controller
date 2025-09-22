#!/usr/bin/env python

"""
Test script for TFT display functionality
This script tests the TFT display without requiring the full kiln controller setup
"""

import sys
import os
import time
import logging

# Add lib directory to path
script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir + '/lib/')

# Import config and create a mock oven for testing
import config
from spi_utils import init_spi_lock, is_spi_lock_initialized

logging.basicConfig(level=config.log_level, format=config.log_format)
log = logging.getLogger("tft-test")

class MockProfile:
    def __init__(self):
        self.name = "Test Profile"

class MockTempSensor:
    def __init__(self):
        self.temp = 75.0 if config.temp_scale.lower() == "f" else 23.9

    def temperature(self):
        # Simulate slowly rising temperature
        self.temp += 0.5
        return self.temp

class MockBoard:
    def __init__(self):
        self.temp_sensor = MockTempSensor()

class MockOven:
    def __init__(self):
        self.board = MockBoard()
        self.state = "RUNNING"
        self.profile = MockProfile()
        self.target = 200.0 if config.temp_scale.lower() == "f" else 93.3
        self.heat = 1.0
        self.heat_rate = 45.2
        self.runtime = 120  # 2 minutes elapsed
        self.totaltime = 3600  # 1 hour total

def main():
    log.info("Testing TFT Display functionality")

    # Initialize SPI lock first
    init_spi_lock()
    log.info(f"SPI lock initialized: {is_spi_lock_initialized()}")

    # Enable TFT display for testing
    config.enable_tft_display = True

    try:
        from tft_display import TFTDisplay

        # Create mock oven
        mock_oven = MockOven()

        # Create and start TFT display
        tft_display = TFTDisplay(mock_oven)
        tft_display.start_display()

        log.info("TFT Display started. Running test for 30 seconds...")
        log.info("You should see temperature, target, and time information on the display")

        # Run for 30 seconds to test display updates
        for i in range(15):  # 15 iterations * 2 seconds = 30 seconds
            time.sleep(2)

            # Update mock data to simulate kiln operation
            mock_oven.runtime += 2
            if i % 3 == 0:  # Change heat status periodically
                mock_oven.heat = 0.0 if mock_oven.heat > 0 else 1.0

            log.info(f"Test iteration {i+1}/15 - Temp: {mock_oven.board.temp_sensor.temperature():.1f}, Target: {mock_oven.target:.1f}")

        log.info("Test completed successfully!")
        tft_display.stop_display()

    except ImportError as e:
        log.error(f"Failed to import TFT display module: {e}")
        log.error("Make sure you have installed: pip install adafruit-circuitpython-rgb-display pillow")
        return 1
    except Exception as e:
        log.error(f"TFT Display test failed: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)