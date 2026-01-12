#!/usr/bin/env python
import requests
import time
import datetime
import logging
import argparse
from enum import Enum

# This monitors your kiln continuously as a service
# Tracks state transitions: OFFLINE -> IDLE -> RUNNING -> IDLE -> OFFLINE
# Sends Slack alerts for important transitions and connection loss during runs

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
log = logging.getLogger(__name__)

class KilnState(Enum):
    """Kiln states tracked by the watcher"""
    OFFLINE = "offline"      # No network connection (Pi/kiln powered off)
    IDLE = "idle"            # Connected but not running a profile
    RUNNING = "running"      # Actively running a kiln profile (includes PAUSED)

    def __str__(self):
        return self.value

class Watcher(object):
    """
    Continuous kiln monitoring service with state machine tracking.

    Monitors kiln state transitions and sends Slack notifications for:
    - Starting a run (IDLE -> RUNNING)
    - Completing a run (RUNNING -> IDLE)
    - Connection loss during run (RUNNING -> OFFLINE) - ALERT!
    - Temperature exceeds max_temp - ALERT!
    - Temperature stuck at error_temp for >60s - ALERT!
    """

    def __init__(self, kiln_url, slack_hook_url, check_interval=10, offline_threshold=60,
                 max_temp=1200, error_temp=32):
        """
        Args:
            kiln_url: Base URL to kiln (e.g., http://192.168.1.84:8081)
            slack_hook_url: Slack incoming webhook URL for notifications
            check_interval: Seconds between status checks (default: 10)
            offline_threshold: Seconds of failed checks before considering OFFLINE (default: 60)
            max_temp: Alert if temperature exceeds this value (default: 1200°F)
            error_temp: Alert if stuck at this temperature for too long (default: 32°F)
        """
        self.kiln_base_url = kiln_url.rstrip('/')
        self.kiln_state_url = f"{self.kiln_base_url}/api/state"
        self.slack_hook_url = slack_hook_url
        self.check_interval = check_interval
        self.offline_threshold = offline_threshold
        self.max_temp = max_temp
        self.error_temp = error_temp

        # State tracking
        self.current_state = KilnState.OFFLINE
        self.last_successful_check = None
        self.consecutive_failures = 0
        self.connection_lost_alert_sent = False

        # Temperature alert tracking
        self.max_temp_alert_sent = False
        self.stuck_temp_start = None
        self.stuck_temp_value = None
        self.stuck_temp_alert_sent = False

        # State data cache
        self.state_data = {}

    def get_state(self):
        """
        Fetch current kiln state from API.

        Returns:
            dict: State data from API including 'state', 'temperature', 'target', etc.
                  Returns empty dict on failure.
        """
        try:
            r = requests.get(self.kiln_state_url, timeout=2)
            if r.status_code == 200:
                return r.json()
            else:
                log.warning(f"API returned status {r.status_code}")
                return {}
        except requests.exceptions.Timeout:
            log.debug("Request timeout")
            return {}
        except requests.exceptions.ConnectionError:
            log.debug("Connection error")
            return {}
        except Exception as e:
            log.debug(f"Unexpected error fetching state: {e}")
            return {}

    def send_notification(self, message, is_alert=False):
        """
        Send a Slack notification.

        Args:
            message: Text message to send
            is_alert: If True, formats as an urgent alert with emoji
        """
        if is_alert:
            message = f"🚨 *ALERT* 🚨\n{message}"

        log.info(f"Sending Slack notification: {message}")
        try:
            r = requests.post(self.slack_hook_url, json={'text': message}, timeout=5)
            if r.status_code != 200:
                log.error(f"Slack API returned status {r.status_code}")
        except Exception as e:
            log.error(f"Failed to send Slack notification: {e}")

    def determine_kiln_state(self):
        """
        Determine current kiln state based on API response.

        Returns:
            KilnState: Current state (OFFLINE, IDLE, or RUNNING)
        """
        # Check if we have recent data
        if not self.state_data or 'state' not in self.state_data:
            # No valid data - check if we've exceeded offline threshold
            if self.last_successful_check is None:
                # First run - assume offline
                return KilnState.OFFLINE

            time_since_last_success = time.time() - self.last_successful_check
            if time_since_last_success >= self.offline_threshold:
                return KilnState.OFFLINE
            else:
                # Within grace period - maintain current state
                return self.current_state

        # We have valid data with 'state' field - use it directly
        api_state = self.state_data['state']

        # Map API state string to our KilnState enum
        # Note: PAUSED is treated as RUNNING per user preference
        if api_state in ("RUNNING", "PAUSED"):
            return KilnState.RUNNING
        elif api_state == "IDLE":
            return KilnState.IDLE
        else:
            log.warning(f"Unknown state from API: {api_state}, assuming IDLE")
            return KilnState.IDLE

    def handle_state_transition(self, new_state):
        """
        Handle state transition and send appropriate notifications.

        Args:
            new_state: The new KilnState
        """
        old_state = self.current_state

        if old_state == new_state:
            return  # No transition

        log.info(f"State transition: {old_state} -> {new_state}")

        # Get temperature info for notifications
        temp = self.state_data.get('temperature', 0)
        target = self.state_data.get('target', 0)

        # Handle transition notifications
        if old_state == KilnState.OFFLINE and new_state == KilnState.IDLE:
            # Kiln powered on - no notification
            log.info("Kiln came online (idle)")

        elif old_state == KilnState.OFFLINE and new_state == KilnState.RUNNING:
            # Rare: came online already running (watcher was down, or very fast startup)
            self.send_notification(
                f"Kiln started running\n"
                f"Current: {temp:.1f}°, Target: {target:.1f}°"
            )

        elif old_state == KilnState.IDLE and new_state == KilnState.RUNNING:
            # Normal: kiln started a run
            #self.send_notification(
            #    f"Kiln started running\n"
            #    f"Current: {temp:.1f}°, Target: {target:.1f}°"
            #)
            pass

        elif old_state == KilnState.RUNNING and new_state == KilnState.IDLE:
            # Run completed successfully
            self.send_notification(
                f"Kiln run completed\n"
                f"Final temperature: {temp:.1f}°"
            )
            # Reset the connection lost flag
            self.connection_lost_alert_sent = False

        elif old_state == KilnState.RUNNING and new_state == KilnState.OFFLINE:
            # CRITICAL: Lost connection during a run!
            if not self.connection_lost_alert_sent:
                self.send_notification(
                    f"Lost connection to kiln during run!\n"
                    f"Last known temp: {temp:.1f}°\n"
                    f"Last known target: {target:.1f}°\n"
                    f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    is_alert=True
                )
                self.connection_lost_alert_sent = True

        elif old_state == KilnState.IDLE and new_state == KilnState.OFFLINE:
            # Normal power-off while idle - no notification
            log.info("Kiln went offline (was idle)")

        # Update current state
        self.current_state = new_state

    def check_temperature_alerts(self):
        """
        Check for temperature-related alerts:
        - Temperature exceeds max_temp
        - Temperature stuck at error_temp for too long
        """
        if not self.state_data or 'temperature' not in self.state_data:
            return

        temp = self.state_data.get('temperature', 0)
        current_time = time.time()

        # Check for max temperature exceeded
        if temp > self.max_temp and not self.max_temp_alert_sent:
            self.send_notification(
                f"Temperature exceeded maximum!\n"
                f"Current: {temp:.1f}°\n"
                f"Maximum: {self.max_temp:.1f}°\n"
                f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                is_alert=True
            )
            self.max_temp_alert_sent = True

        # Reset max temp alert if temperature drops below threshold
        if temp <= self.max_temp - 10:  # 10 degree hysteresis to avoid flapping
            self.max_temp_alert_sent = False

        # Check for stuck temperature (within ±1 degree of error_temp)
        temp_range_low = self.error_temp - 1
        temp_range_high = self.error_temp + 1

        if temp_range_low <= temp <= temp_range_high:
            # Temperature is in the error range
            if self.stuck_temp_start is None:
                # Start tracking stuck temperature
                self.stuck_temp_start = current_time
                self.stuck_temp_value = temp
                log.debug(f"Temperature entered error range: {temp:.1f}°")
            else:
                # Check if we've been stuck for more than 60 seconds
                stuck_duration = current_time - self.stuck_temp_start
                if stuck_duration >= 180 and not self.stuck_temp_alert_sent:
                    self.send_notification(
                        f"Temperature stuck at error value!\n"
                        f"Current: {temp:.1f}°\n"
                        f"Expected range: {temp_range_low:.1f}° - {temp_range_high:.1f}°\n"
                        f"Duration: {int(stuck_duration)}s\n"
                        f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        is_alert=True
                    )
                    self.stuck_temp_alert_sent = True
        else:
            # Temperature is outside error range - reset tracking
            if self.stuck_temp_start is not None:
                log.debug(f"Temperature left error range: {temp:.1f}°")
            self.stuck_temp_start = None
            self.stuck_temp_value = None
            self.stuck_temp_alert_sent = False

    def run(self):
        """
        Main monitoring loop - runs continuously as a service.
        """
        log.info(f"Kiln watcher started - monitoring {self.kiln_state_url}")
        log.info(f"Check interval: {self.check_interval}s, Offline threshold: {self.offline_threshold}s")

        while True:
            try:
                # Fetch current state
                self.state_data = self.get_state()

                # Update failure tracking
                if self.state_data and 'state' in self.state_data:
                    self.last_successful_check = time.time()
                    self.consecutive_failures = 0

                    # Log current status
                    temp = self.state_data.get('temperature', 0)
                    target = self.state_data.get('target', 0)
                    state = self.state_data.get('state', 'unknown')
                    runtime = self.state_data.get('runtime', 0)
                    log.info(f"OK - State: {state}, Temp: {temp:.1f}°, Target: {target:.1f}°, Runtime: {runtime}s")
                else:
                    self.consecutive_failures += 1
                    log.warning(f"Failed to get state (failure {self.consecutive_failures})")

                # Determine new state
                new_state = self.determine_kiln_state()

                # Handle any state transitions
                self.handle_state_transition(new_state)

                # Check for temperature alerts
                self.check_temperature_alerts()

            except Exception as e:
                log.error(f"Error in monitoring loop: {e}", exc_info=True)

            # Sleep until next check
            time.sleep(self.check_interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Kiln Watcher - Continuous monitoring service for kiln controller',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--slack-hook',
        type=str,
        required=True,
        help='Slack incoming webhook URL for notifications'
    )
    parser.add_argument(
        '--kiln-url',
        type=str,
        default='http://192.168.87.23:8081',
        help='Base URL to kiln controller'
    )
    parser.add_argument(
        '--check-interval',
        type=int,
        default=10,
        help='Seconds between status checks'
    )
    parser.add_argument(
        '--offline-threshold',
        type=int,
        default=60,
        help='Seconds of failed checks before considering offline'
    )
    parser.add_argument(
        '--max-temp',
        type=float,
        default=1200,
        help='Alert if temperature exceeds this value (°F)'
    )
    parser.add_argument(
        '--error-temp',
        type=float,
        default=32,
        help='Alert if stuck at this temperature (±1°) for >60 seconds'
    )

    args = parser.parse_args()

    watcher = Watcher(
        kiln_url=args.kiln_url,
        slack_hook_url=args.slack_hook,
        check_interval=args.check_interval,
        offline_threshold=args.offline_threshold,
        max_temp=args.max_temp,
        error_temp=args.error_temp
    )

    try:
        watcher.run()
    except KeyboardInterrupt:
        log.info("Watcher stopped by user")
    except Exception as e:
        log.error(f"Watcher crashed: {e}", exc_info=True)
