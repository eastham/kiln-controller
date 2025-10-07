#!/usr/bin/env python

"""
Watchdog Thread for Kiln Controller Safety

Monitors critical threads and reboots the system if any thread becomes unresponsive.
This is essential safety functionality to prevent runaway heating if software hangs.
"""

import threading
import time
import logging
import os
import sys

log = logging.getLogger(__name__)

class WatchdogMonitor(threading.Thread):
    """
    Safety watchdog that monitors critical threads and reboots if any hang

    Each monitored thread must update its timestamp at least every 20 seconds.
    The watchdog checks every second and will emergency shutdown + reboot if
    any thread hasn't updated within the timeout period.
    """

    def __init__(self, oven):
        threading.Thread.__init__(self)
        self.daemon = False  # Don't die with main program - we need to stay alive for safety
        self.oven = oven    # Reference to oven for emergency shutdown
        self.running = False

        # Watchdog configuration
        self.CHECK_INTERVAL = 1.0      # Check every second
        self.THREAD_TIMEOUT = 25.0     # Threads must update within 20 seconds

        # Thread monitoring registry
        # Each thread registers itself and must update its timestamp regularly
        self.monitored_threads = {}
        self.lock = threading.Lock()

        log.info("Watchdog monitor initialized")

    def register_thread(self, thread_name, description=""):
        """Register a thread for monitoring"""
        with self.lock:
            self.monitored_threads[thread_name] = {
                'last_update': time.time(),
                'description': description,
                'initialized': True
            }
        log.info(f"Watchdog: Registered thread '{thread_name}' - {description}")

    def unregister_thread(self, thread_name):
        """Unregister a thread (for clean shutdown)"""
        with self.lock:
            if thread_name in self.monitored_threads:
                del self.monitored_threads[thread_name]
                log.info(f"Watchdog: Unregistered thread '{thread_name}'")

    def update_thread_timestamp(self, thread_name):
        """Update timestamp for a monitored thread"""
        with self.lock:
            if thread_name in self.monitored_threads:
                self.monitored_threads[thread_name]['last_update'] = time.time()

    def check_threads(self):
        """Check all monitored threads for timeouts"""
        current_time = time.time()
        hung_threads = []

        with self.lock:
            for thread_name, info in self.monitored_threads.items():
                time_since_update = current_time - info['last_update']

                if time_since_update > self.THREAD_TIMEOUT:
                    hung_threads.append({
                        'name': thread_name,
                        'description': info['description'],
                        'timeout': time_since_update
                    })

        return hung_threads

    def emergency_shutdown_and_reboot(self, hung_threads):
        """Emergency shutdown and system reboot due to hung threads"""
        log.critical("WATCHDOG EMERGENCY: Hung threads detected - initiating emergency shutdown and reboot")

        for thread_info in hung_threads:
            log.critical(f"Hung thread: {thread_info['name']} ({thread_info['description']}) - "
                        f"timeout: {thread_info['timeout']:.1f}s")

        # CRITICAL: Turn off heat immediately for safety
        try:
            if self.oven:
                self.oven.abort_run()
                log.critical("WATCHDOG: Emergency heat shutdown completed")
        except Exception as e:
            log.critical(f"WATCHDOG: Failed to turn off heat during emergency: {e}")

        # Give a moment for heat shutdown to complete
        time.sleep(1)

        # Log final emergency message
        log.critical("WATCHDOG: Initiating system reboot for safety")

        # Force immediate system reboot
        # Using sync first to flush filesystem buffers
        try:
            os.system("sync")
            time.sleep(0.5)
            os.system("sudo reboot")
        except Exception as e:
            log.critical(f"WATCHDOG: Reboot command failed: {e}")

        # If reboot fails, try harder shutdown methods
        try:
            os.system("sudo shutdown -r now")
            time.sleep(1)
            # Last resort - force kernel panic (will cause reboot on most systems)
            with open('/proc/sysrq-trigger', 'w') as f:
                f.write('b')
        except Exception:
            # Final fallback - exit the process
            log.critical("WATCHDOG: All reboot methods failed - exiting process")
            os._exit(1)

    def start_watchdog(self):
        """Start the watchdog monitoring"""
        self.running = True
        self.start()
        log.info("Watchdog monitoring started - checking every 1 second, 20 second timeout")

    def stop_watchdog(self):
        """Stop the watchdog monitoring"""
        self.running = False
        log.info("Watchdog monitoring stopped")

    def run(self):
        """Main watchdog monitoring loop"""
        log.info("Watchdog thread started")

        while self.running:
            try:
                # Check for hung threads
                hung_threads = self.check_threads()

                if hung_threads:
                    # CRITICAL SAFETY ISSUE - hung threads detected
                    self.emergency_shutdown_and_reboot(hung_threads)
                    # Should never reach here due to reboot
                    break

                # Sleep until next check
                time.sleep(self.CHECK_INTERVAL)

            except Exception as e:
                log.error(f"Error in watchdog monitoring loop: {e}")
                time.sleep(self.CHECK_INTERVAL)

        log.info("Watchdog thread stopped")

# Global watchdog instance
_watchdog = None

def init_watchdog(oven):
    """Initialize the global watchdog monitor"""
    global _watchdog
    _watchdog = WatchdogMonitor(oven)
    return _watchdog

def get_watchdog():
    """Get the global watchdog instance"""
    return _watchdog

def start_watchdog():
    """Start the global watchdog"""
    if _watchdog:
        _watchdog.start_watchdog()

def stop_watchdog():
    """Stop the global watchdog"""
    if _watchdog:
        _watchdog.stop_watchdog()

def register_thread(thread_name, description=""):
    """Register current thread for watchdog monitoring"""
    if _watchdog:
        _watchdog.register_thread(thread_name, description)

def unregister_thread(thread_name):
    """Unregister current thread from watchdog monitoring"""
    if _watchdog:
        _watchdog.unregister_thread(thread_name)

def update_watchdog(thread_name=None):
    """Update timestamp for current thread (call this regularly from monitored threads)"""
    if _watchdog:
        if thread_name is None:
            thread_name = threading.current_thread().name
        _watchdog.update_thread_timestamp(thread_name)