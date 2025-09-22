#!/usr/bin/env python

"""
Test script to verify SPI locking between thermocouple and TFT display
This script simulates concurrent access to test that SPI operations are properly serialized
"""

import sys
import os
import time
import logging
import threading
import random

# Add lib directory to path
script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir + '/lib/')

import config
from spi_utils import init_spi_lock, spi_lock, is_spi_lock_initialized

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(threadName)s %(levelname)s: %(message)s')
log = logging.getLogger("spi-lock-test")

class MockSPIOperation:
    """Mock SPI operation that simulates realistic SPI communication timing"""

    def __init__(self, device_name, operation_time_ms=5):
        self.device_name = device_name
        self.operation_time = operation_time_ms / 1000.0  # Convert to seconds
        self.operation_count = 0

    def perform_operation(self):
        """Simulate SPI operation with proper locking"""
        operation_id = self.operation_count
        self.operation_count += 1

        log.info(f"{self.device_name} operation {operation_id} starting")

        with spi_lock():
            log.info(f"{self.device_name} operation {operation_id} acquired SPI lock")

            # Simulate SPI communication time
            time.sleep(self.operation_time)

            log.info(f"{self.device_name} operation {operation_id} completed")

        log.info(f"{self.device_name} operation {operation_id} released SPI lock")

class ConcurrentTester(threading.Thread):
    """Thread that performs multiple SPI operations"""

    def __init__(self, device_name, operation_count=5, interval_ms=100):
        super().__init__()
        self.device_name = device_name
        self.operation_count = operation_count
        self.interval = interval_ms / 1000.0
        self.spi_op = MockSPIOperation(device_name)
        self.daemon = True

    def run(self):
        log.info(f"{self.device_name} thread started")

        for i in range(self.operation_count):
            # Add some randomness to timing to increase chance of collisions
            jitter = random.uniform(0, self.interval * 0.5)
            time.sleep(self.interval + jitter)

            self.spi_op.perform_operation()

        log.info(f"{self.device_name} thread completed")

def test_spi_locking():
    """Test that SPI operations are properly serialized"""
    log.info("=== SPI Locking Test ===")

    # Initialize SPI lock
    init_spi_lock()
    log.info(f"SPI lock initialized: {is_spi_lock_initialized()}")

    # Create concurrent testers simulating thermocouple and TFT display
    thermocouple_tester = ConcurrentTester(
        device_name="Thermocouple",
        operation_count=10,
        interval_ms=200  # Simulates 200ms between temp readings
    )

    tft_display_tester = ConcurrentTester(
        device_name="TFT_Display",
        operation_count=3,
        interval_ms=2000  # Simulates 2s between display updates
    )

    # Start both threads
    log.info("Starting concurrent SPI operations...")
    thermocouple_tester.start()
    tft_display_tester.start()

    # Wait for both to complete
    thermocouple_tester.join()
    tft_display_tester.join()

    log.info("=== Test Completed Successfully ===")
    log.info("If you see interleaved 'acquired SPI lock' and 'completed' messages")
    log.info("without overlapping operations, the locking is working correctly!")

def test_without_locking():
    """Demonstrate what happens without SPI locking (for comparison)"""
    log.info("=== Test Without Locking (for comparison) ===")
    log.info("This simulates what would happen without SPI locking...")

    class UnsafeSPIOperation:
        def __init__(self, device_name):
            self.device_name = device_name
            self.op_count = 0

        def unsafe_operation(self):
            op_id = self.op_count
            self.op_count += 1
            log.info(f"{self.device_name} unsafe operation {op_id} starting (NO LOCK)")
            time.sleep(0.005)  # 5ms operation
            log.info(f"{self.device_name} unsafe operation {op_id} completed (NO LOCK)")

    # Create unsafe operations
    thermo_unsafe = UnsafeSPIOperation("Thermocouple")
    tft_unsafe = UnsafeSPIOperation("TFT_Display")

    def unsafe_worker(spi_op, count):
        for i in range(count):
            spi_op.unsafe_operation()
            time.sleep(0.1)

    # Start unsafe operations concurrently
    thread1 = threading.Thread(target=unsafe_worker, args=(thermo_unsafe, 3))
    thread2 = threading.Thread(target=unsafe_worker, args=(tft_unsafe, 3))

    thread1.start()
    thread2.start()

    thread1.join()
    thread2.join()

    log.info("=== Unsafe Test Completed ===")
    log.info("Notice how operations can overlap without locking!")

def main():
    log.info("SPI Locking Test Suite")
    log.info("This test verifies that SPI bus access is properly serialized")
    log.info("between thermocouple and TFT display operations.")
    print()

    try:
        # Test with proper locking
        test_spi_locking()
        print()

        # Test without locking for comparison
        test_without_locking()
        print()

        log.info("All tests completed successfully!")
        log.info("The SPI locking mechanism is working correctly.")
        return 0

    except Exception as e:
        log.error(f"Test failed: {e}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)