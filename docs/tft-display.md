# TFT Display Support

This document describes how to set up and use the Adafruit Mini PiTFT - 135x240 Color TFT display with the kiln controller.

## Overview

The TFT display feature provides a real-time visual display showing:
- Current kiln temperature
- Target temperature
- Time remaining in firing schedule
- Kiln status (IDLE, RUNNING, PAUSED)
- Heat status (ON/OFF)
- Heating rate (degrees per hour)
- Current profile name

## Hardware Requirements

- Adafruit Mini PiTFT - 135x240 Color TFT Add-on for Raspberry Pi (Product ID: 4393)
- Raspberry Pi with SPI enabled

## Hardware Setup

### Wiring Connections

The Mini PiTFT shares the SPI bus with the thermocouple board. Both devices use the same SPI clock, MOSI, and MISO lines, but have separate chip select (CS) pins.

| TFT Pin | RPi Pin | BCM Pin | Function |
|---------|---------|---------|----------|
| CS      | CE0     | GPIO8   | TFT Chip Select (hardware SPI CE0) |
| DC      | GPIO19  | GPIO19  | Data/Command (TFT-specific signal) |
| RST     | GPIO26  | GPIO26  | Reset (TFT-specific signal) |
| SPI SCLK| SCLK    | GPIO11  | SPI Clock (shared with thermocouple) |
| SPI MOSI| MOSI    | GPIO10  | SPI Data Out (shared with thermocouple) |
| SPI MISO| MISO    | GPIO9   | SPI Data In (shared with thermocouple) |
| VCC     | 3.3V    | -       | Power |
| GND     | GND     | -       | Ground |

**Important:** Both devices use hardware SPI with different chip selects:
- **Thermocouple**: CE1 (GPIO7)
- **TFT Display**: CE0 (GPIO8)

### SPI Bus Sharing

The kiln controller now supports two SPI devices on the same bus:

1. **Thermocouple Board** (MAX31855/MAX31856)
   - CS: CE1/GPIO7 (configurable as `spi_cs` in config.py)
   - Standard SPI device for temperature reading

2. **TFT Display** (ST7789 controller)
   - CS: CE0/GPIO8 (configurable as `tft_cs_pin` in config.py)
   - DC: GPIO19 (Data/Command control - display specific)
   - RST: GPIO26 (Reset - display specific)

Both devices share the SPI bus signals (SCLK, MOSI, MISO) but use different chip select pins. The DC and Reset pins are specific to the display controller and not part of the standard SPI interface.

### Enable SPI

Enable SPI on your Raspberry Pi:
```bash
sudo raspi-config
# Navigate to: Interfacing Options -> SPI -> Enable
sudo reboot
```

## Software Installation

### Install Required Libraries

```bash
# Activate your virtual environment
source venv/bin/activate

# Install TFT display dependencies
pip install adafruit-circuitpython-rgb-display pillow

# Install system fonts (optional but recommended)
sudo apt-get install fonts-dejavu
```

### Enable TFT Display in Configuration

Edit `config.py` and set:
```python
enable_tft_display = True
```

## Usage

### Starting the Kiln Controller with TFT Display

```bash
source venv/bin/activate
./kiln-controller.py
```

If the TFT display is properly connected and configured, you should see:
- "TFT display enabled and started" in the log output
- The display will show the current kiln status

### Testing the Display

To test the TFT display without running a full kiln firing:

```bash
source venv/bin/activate
./test-tft-display.py
```

This will run a 30-second test showing mock temperature data on the display.

## Display Layout

The display is organized into several sections:

### Status Bar (Top)
- Shows current kiln state (IDLE, RUNNING, PAUSED)
- Shows active profile name when running

### Temperature Section
- **Current:** Shows the actual kiln temperature with unit (°F or °C)
- **Target:** Shows the target temperature from the firing schedule

### Time Section
- **Time Left:** Shows remaining time in HH:MM:SS format

### Heat Section
- **Heat:** Shows "HEATING" (red) or "OFF" (gray)
- **Rate:** Shows current heating rate in degrees per hour

## Color Coding

- **Green:** Normal operation (RUNNING state, time remaining)
- **Yellow:** Target temperature, PAUSED state
- **Red:** Heating status when active
- **Gray:** Inactive states
- **White:** General text and temperature readings

## Troubleshooting

### Display Not Working

1. **Check SPI is enabled:**
   ```bash
   lsmod | grep spi
   ```

2. **Verify wiring connections**
   - Double-check all connections match the wiring table
   - Ensure good electrical connections

3. **Check Python dependencies:**
   ```bash
   pip list | grep adafruit
   pip list | grep pillow
   ```

4. **Test basic display functionality:**
   ```bash
   ./test-tft-display.py
   ```

### Display Shows But No Updates

1. **Check configuration:**
   - Ensure `enable_tft_display = True` in config.py
   - Restart kiln-controller.py after configuration changes

2. **Check log output:**
   - Look for TFT display related error messages
   - Verify "TFT display enabled and started" appears in logs

### Performance Issues

1. **Reduce update frequency (if needed):**
   - The display updates every 2 seconds by default
   - This matches the `sensor_time_wait` setting

2. **Font loading issues:**
   - If DejaVu fonts are not available, the system will fall back to default fonts
   - Install fonts with: `sudo apt-get install fonts-dejavu`

## Customization

The display layout and colors can be customized by editing `lib/tft_display.py`:

- **Colors:** Modify the RGB color definitions in `__init__()`
- **Fonts:** Change font paths and sizes in `init_display()`
- **Layout:** Modify the drawing functions to change positioning and content
- **Update Rate:** Change the sleep time in the `run()` method

## Disabling the Display

To disable the TFT display feature:

1. Set `enable_tft_display = False` in config.py
2. Restart the kiln controller

The display will be cleared and the feature disabled without affecting other kiln controller functionality.

## Integration Notes

- The TFT display runs in its own thread and does not affect kiln control timing
- Display updates are synchronized with the main sensor reading cycle
- Graceful shutdown is handled when the kiln controller is stopped
- The feature is designed to be optional and not interfere with existing functionality