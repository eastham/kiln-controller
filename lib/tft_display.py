#!/usr/bin/env python

import threading
import time
import logging
import board
import digitalio
from PIL import Image, ImageDraw, ImageFont
import adafruit_rgb_display.st7789 as st7789
import config
from spi_utils import spi_lock

log = logging.getLogger(__name__)

class TFTDisplay(threading.Thread):
    """
    Display current temp, target temp, and time remaining on Adafruit Mini PiTFT - 135x240 Color TFT
    """

    def __init__(self, oven):
        threading.Thread.__init__(self)
        self.daemon = True  # Thread dies when main program exits
        self.oven = oven    # Reference to kiln oven object
        self.running = False  # Thread control flag

        # Display configuration
        self.width = 135   # Physical width (before rotation)
        self.height = 240  # Physical height (before rotation)
        self.rotation = 90  # Landscape orientation (swaps dimensions)

        # Colors (R, G, B)
        self.BLACK = (0, 0, 0)
        self.WHITE = (255, 255, 255)
        self.RED = (255, 0, 0)
        self.GREEN = (0, 255, 0)
        self.BLUE = (0, 0, 255)
        self.YELLOW = (255, 255, 0)
        self.ORANGE = (255, 165, 0)
        self.GRAY = (128, 128, 128)

        # Program selection mode (for GPIO buttons)
        self.selection_mode = False      # True when showing program selection
        self.selected_profile = None     # Currently selected profile data
        self.message_mode = False        # True when showing temporary message
        self.message_text = ""           # Message to display
        self.message_expire_time = 0     # When message expires

        self.init_display()

    def init_display(self):
        """Initialize the TFT display"""
        try:
            # Configure display pins from config
            cs_pin = digitalio.DigitalInOut(config.tft_cs_pin)
            dc_pin = digitalio.DigitalInOut(config.tft_dc_pin)
            reset_pin = digitalio.DigitalInOut(config.tft_reset_pin)

            # Initialize display with offset parameters for proper alignment
            self.disp = st7789.ST7789(
                board.SPI(),
                rotation=self.rotation,
                width=self.width,
                height=self.height,
                x_offset=53,       # X offset for 135x240 display (per Adafruit docs)
                y_offset=40,       # Y offset for 135x240 display (per Adafruit docs)
                cs=cs_pin,
                dc=dc_pin,
                rst=reset_pin,
                baudrate=4000000   # Slower speed for more reliable operation
            )

            # Create drawing objects using rotated dimensions
            # With 90 degree rotation, width and height are swapped for the image
            log.info(f"Display dimensions after init: {self.disp.width} x {self.disp.height}")
            log.info(f"Physical dimensions: {self.width} x {self.height}")

            # For 90-degree rotation, we need to use the actual display dimensions
            # The display reports 135x240 but with rotation=90, drawing area is 240x135
            self.draw_width = 240   # Effective width after rotation
            self.draw_height = 135  # Effective height after rotation

            log.info("Creating image with dimensions: {} x {}".format(self.draw_width, self.draw_height))
            self.image = Image.new("RGB", (self.draw_width, self.draw_height))
            self.draw = ImageDraw.Draw(self.image)

            # Load fonts
            try:
                self.font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
                self.font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
                self.font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
            except OSError:
                # Fallback to default font if DejaVu not available
                self.font_large = ImageFont.load_default()
                self.font_medium = ImageFont.load_default()
                self.font_small = ImageFont.load_default()
                log.warning("Could not load DejaVu fonts, using default font")

            # Clear display
            self.clear_display()
            log.info("TFT Display initialized successfully")

        except Exception as e:
            log.error(f"Failed to initialize TFT display: {e}")
            self.disp = None

    def clear_display(self):
        """Clear the display with black background"""
        if self.disp:
            self.draw.rectangle((0, 0, self.draw_width, self.draw_height), fill=self.BLACK)
            with spi_lock():
                self.disp.image(self.image)

    def format_temperature(self, temp):
        """Format temperature with appropriate unit"""
        if temp is None:
            return "---"

        unit = "°F" if config.temp_scale.lower() == "f" else "°C"
        return f"{temp:.1f}{unit}"

    def format_time(self, seconds):
        """Format time in HH:MM:SS format"""
        if seconds <= 0:
            return "00:00:00"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def get_status_color(self):
        """Get status color based on kiln state"""
        if not hasattr(self.oven, 'state'):
            return self.GRAY

        state = self.oven.state
        if state == "RUNNING":
            return self.GREEN
        elif state == "PAUSED":
            return self.YELLOW
        elif state == "IDLE":
            return self.GRAY
        else:
            return self.RED

    def draw_status_bar(self):
        """Draw status bar at top of display"""
        # Status bar background
        status_color = self.get_status_color()
        self.draw.rectangle((0, 0, self.draw_width, 20), fill=status_color)

        # Status text
        status_text = getattr(self.oven, 'state', 'UNKNOWN')
        profile_name = getattr(self.oven.profile, 'name', '') if hasattr(self.oven, 'profile') and self.oven.profile else ''

        if profile_name:
            status_text += f" - {profile_name}"

        self.draw.text((5, 2), status_text, font=self.font_small, fill=self.BLACK)

    def draw_temperature_section(self, y_start):
        """Draw current and target temperature section"""
        section_height = 50

        # Section background
        self.draw.rectangle((0, y_start, self.draw_width, y_start + section_height),
                           fill=self.BLACK, outline=self.WHITE)

        # Current temperature
        try:
            current_temp = self.oven.board.temp_sensor.temperature() + config.thermocouple_offset
        except:
            current_temp = None

        current_temp_str = self.format_temperature(current_temp)
        self.draw.text((5, y_start + 3), "Current:", font=self.font_small, fill=self.WHITE)
        self.draw.text((5, y_start + 18), current_temp_str, font=self.font_medium, fill=self.WHITE)

        # Target temperature
        target_temp = getattr(self.oven, 'target', 0)
        target_temp_str = self.format_temperature(target_temp)
        self.draw.text((5, y_start + 38), "Target: {}".format(target_temp_str),
                      font=self.font_small, fill=self.YELLOW)

        return y_start + section_height

    def draw_time_section(self, y_start):
        """Draw time remaining section"""
        section_height = 35

        # Section background
        self.draw.rectangle((0, y_start, self.draw_width, y_start + section_height),
                           fill=self.BLACK, outline=self.WHITE)

        # Calculate time remaining
        total_time = getattr(self.oven, 'totaltime', 0)
        runtime = getattr(self.oven, 'runtime', 0)
        time_remaining = max(0, total_time - runtime)

        time_str = self.format_time(time_remaining)

        self.draw.text((5, y_start + 3), "Time Left:", font=self.font_small, fill=self.WHITE)
        self.draw.text((5, y_start + 18), time_str, font=self.font_small, fill=self.GREEN)

        return y_start + section_height

    def draw_heat_section(self, y_start):
        """Draw heating status section"""
        section_height = 30

        # Section background
        self.draw.rectangle((0, y_start, self.draw_width, y_start + section_height),
                           fill=self.BLACK, outline=self.WHITE)

        # Heat status
        heat_on = getattr(self.oven, 'heat', 0) > 0
        heat_text = "HEATING" if heat_on else "OFF"
        heat_color = self.RED if heat_on else self.GRAY

        self.draw.text((5, y_start + 3), "Heat:", font=self.font_small, fill=self.WHITE)
        self.draw.text((5, y_start + 15), heat_text, font=self.font_small, fill=heat_color)

        # Heat rate if available
        if hasattr(self.oven, 'heat_rate'):
            rate_unit = "°F/hr" if config.temp_scale.lower() == "f" else "°C/hr"
            rate_text = "{:.1f} {}".format(self.oven.heat_rate, rate_unit)
            self.draw.text((80, y_start + 15), rate_text, font=self.font_small, fill=self.WHITE)

        return y_start + section_height

    def update_display(self):
        """Update the display with current kiln status"""
        if not self.disp:
            return

        try:
            # Clear display
            self.draw.rectangle((0, 0, self.draw_width, self.draw_height), fill=self.BLACK)

            # Check for special display modes
            if self.message_mode and time.time() < self.message_expire_time:
                self.draw_message()
            elif self.selection_mode and self.selected_profile:
                self.draw_program_selection()
            else:
                # Normal kiln status display
                self.draw_normal_status()

            # Update display
            with spi_lock():
                self.disp.image(self.image)

        except Exception as e:
            log.error(f"Error updating TFT display: {e}")

    def draw_normal_status(self):
        """Draw normal kiln status display"""
        # Draw sections
        y_pos = 0

        # Status bar
        self.draw_status_bar()
        y_pos += 25

        # Temperature section
        y_pos = self.draw_temperature_section(y_pos)
        y_pos += 2

        # Time section
        y_pos = self.draw_time_section(y_pos)
        y_pos += 2

        # Heat section
        self.draw_heat_section(y_pos)

    def draw_program_selection(self):
        """Draw program selection display"""
        profile = self.selected_profile

        # Title
        self.draw.text((5, 5), "Selected Program:", font=self.font_small, fill=self.WHITE)

        # Program name (truncate if too long)
        name = profile['name']
        if len(name) > 18:
            name = name[:15] + "..."
        self.draw.text((5, 25), name, font=self.font_medium, fill=self.YELLOW)

        # Max temp and duration
        temp_unit = "°F" if config.temp_scale.lower() == "f" else "°C"
        duration_text = f"Max: {profile['max_temp']:.0f}{temp_unit}  {profile['duration']:.1f}h"
        self.draw.text((5, 50), duration_text, font=self.font_small, fill=self.WHITE)

        # Button hints
        self.draw.text((5, 75), "[CYCLE] [START]", font=self.font_small, fill=self.GREEN)

    def draw_message(self):
        """Draw temporary message"""
        # Center the message
        message_lines = self.message_text.split('\n')
        y_start = (self.draw_height - len(message_lines) * 20) // 2

        for i, line in enumerate(message_lines):
            self.draw.text((5, y_start + i * 20), line, font=self.font_medium, fill=self.YELLOW)

    def set_selection_mode(self, profile):
        """Enter program selection mode"""
        self.selection_mode = True
        self.selected_profile = profile
        self.message_mode = False  # Clear any active message

    def exit_selection_mode(self):
        """Exit program selection mode"""
        self.selection_mode = False
        self.selected_profile = None

    def show_message(self, message, duration_seconds):
        """Show temporary message"""
        self.message_mode = True
        self.message_text = message
        self.message_expire_time = time.time() + duration_seconds
        self.selection_mode = False  # Clear selection mode

    def start_display(self):
        """Start the display update thread"""
        if self.disp:
            self.running = True
            self.start()
            log.info("TFT Display thread started")
        else:
            log.error("Cannot start display - initialization failed")

    def stop_display(self):
        """Stop the display update thread"""
        self.running = False
        if self.disp:
            self.clear_display()
        log.info("TFT Display stopped")

    def run(self):
        """Main display update loop"""
        log.info("TFT Display update loop started")

        while self.running:
            try:
                self.update_display()
                time.sleep(2)  # Update every 2 seconds to match sensor_time_wait
            except Exception as e:
                log.error(f"Error in TFT display loop: {e}")
                time.sleep(5)  # Wait longer on error

        log.info("TFT Display update loop stopped")


# Factory function to create display if enabled
def create_tft_display(oven):
    """Create TFT display if enabled in config"""
    if hasattr(config, 'enable_tft_display') and config.enable_tft_display:
        try:
            return TFTDisplay(oven)
        except Exception as e:
            log.error(f"Failed to create TFT display: {e}")
            return None
    return None