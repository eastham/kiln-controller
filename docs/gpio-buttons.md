# GPIO Button Control

This document describes how to set up and use physical GPIO buttons for direct kiln control without requiring web interface access.

## Overview

The GPIO button feature provides two physical buttons for kiln operation:

1. **Program Cycle Button**: Cycles through available firing profiles (IDLE state only)
2. **Start/Stop Button**: Starts selected program or stops running program

## Hardware Requirements

- 2x GPIO pins for button inputs
- 2x momentary push buttons (normally open)
- 2x pull-up resistors (10kΩ recommended)
- Raspberry Pi with available GPIO pins

## Hardware Setup

### Wiring Connections

Connect the buttons to GPIO pins with pull-up resistors:

| Component | Connection | Notes |
|-----------|------------|-------|
| Program Button | GPIO26 (configurable) | One side to GPIO, other to GND |
| Start/Stop Button | GPIO19 (configurable) | One side to GPIO, other to GND |
| Pull-up Resistors | GPIO to 3.3V | 10kΩ resistors for each button |

### Wiring Diagram
```
3.3V ----[10kΩ]---- GPIO26 ---- Button ---- GND
3.3V ----[10kΩ]---- GPIO19 ---- Button ---- GND
```

**Note**: The software uses internal pull-up resistors, but external resistors provide more reliable operation.

## Software Configuration

### Enable GPIO Buttons

Edit `config.py` and set:
```python
enable_gpio_buttons = True
```

### Configure GPIO Pins

The default GPIO pins can be changed in `config.py`:
```python
gpio_program_button = board.D26    # Program cycle button
gpio_startstop_button = board.D19  # Start/stop button
```

Available GPIO pins on Raspberry Pi (avoid pins already used by thermocouple/TFT):
- Available: D5, D6, D12, D13, D16, D19, D20, D21, D26
- Used by thermocouple: D22 (CS), D17 (SCLK), D27 (MISO), D10 (MOSI)
- Used by TFT: D8 (CS), D25 (DC), D24 (Reset)
- Used by kiln relay: D23

## Button Operation

### Program Cycle Button

**Function**: Cycles through available firing profiles

**Behavior**:
- Only works when kiln is in IDLE state
- First press: Enters program selection mode, shows first profile
- Subsequent presses: Cycles to next profile
- Auto-timeout: Returns to normal display after 30 seconds of inactivity
- Disabled: Button ignored when kiln is RUNNING or PAUSED

**Display**: Shows selected program name, max temperature, and duration

### Start/Stop Button

**Function**: Controls kiln operation based on current state

**Behavior**:
- **IDLE + program selected**: Starts the selected firing profile
- **IDLE + no selection**: Shows "No program selected" message
- **RUNNING**: Stops current firing (same as web "Stop" button)
- **PAUSED**: Resumes firing (utilizes existing resume functionality)

### TFT Display Integration

When program selection is active, the TFT display shows:
```
Selected Program:
cone-05-fast-bisque
Max: 1888°F  8.6h
[CYCLE] [START]
```

## Usage Instructions

### Starting a Kiln Run

1. Ensure kiln is in IDLE state
2. Press **Program Cycle** button to enter selection mode
3. Press **Program Cycle** repeatedly to find desired profile
4. Press **Start/Stop** button to begin firing
5. Display returns to normal kiln status

### Stopping a Kiln Run

1. Press **Start/Stop** button while kiln is RUNNING
2. Kiln will stop immediately (same as web interface)

### Program Selection Timeout

- Selection mode automatically exits after 30 seconds of inactivity
- Display returns to normal kiln status
- No profile is started

## Safety Features

### State Validation
- Program button only works in IDLE state
- Start button validates profile selection
- Stop button always works (emergency stop capability)

### Debouncing
- 0.5 second debounce prevents multiple triggers
- Mechanical button bounce is filtered out

### API Integration
- Uses existing `/api` endpoints for start/stop operations
- Maintains all existing safety checks and validation
- Consistent behavior with web interface

## Testing

### Software Testing

Test the button functionality without hardware:
```bash
source venv/bin/activate
./test-gpio-buttons.py
```

This script simulates button presses and validates:
- Profile loading and cycling
- Button state management
- Selection timeout behavior
- API command simulation

### Hardware Testing

With actual buttons connected:
1. Enable GPIO buttons in config.py
2. Start kiln controller: `./kiln-controller.py`
3. Test program cycling in IDLE state
4. Test start/stop functionality
5. Verify TFT display updates

## Troubleshooting

### Buttons Not Responding

1. **Check GPIO pins**:
   ```bash
   # Test GPIO pin state
   ./gpioreadall.py
   ```

2. **Verify wiring**:
   - Ensure buttons connect GPIO to GND
   - Check pull-up resistor connections
   - Test button continuity with multimeter

3. **Check configuration**:
   - Ensure `enable_gpio_buttons = True`
   - Verify GPIO pin assignments match wiring
   - Restart kiln controller after config changes

### False Button Presses

1. **Increase debounce time** in gpio_buttons.py:
   ```python
   self.DEBOUNCE_TIME = 1.0  # Increase from 0.5
   ```

2. **Check for electrical interference**:
   - Add capacitors across button contacts (0.1µF)
   - Ensure clean power supply
   - Keep button wires away from high-current circuits

### Display Not Updating

1. **Check TFT display** is enabled and working
2. **Verify button manager** starts successfully in logs
3. **Test without TFT** - buttons work independently

## Integration Notes

### Compatibility
- Works with existing web interface
- Compatible with TFT display feature
- Maintains all safety interlocks
- Does not interfere with automatic restarts

### Performance
- Minimal CPU overhead (0.1s polling interval)
- No impact on kiln control timing
- Thread-safe operation

### Extensibility
- Easy to add more buttons by extending ButtonManager
- Can add additional button functions (pause/resume, emergency stop)
- Display can show additional information

## File Structure

```
lib/gpio_buttons.py          # Button management and profile cycling
lib/tft_display.py           # Modified: Program selection display
config.py                    # Modified: GPIO button configuration
kiln-controller.py           # Modified: Button manager integration
test-gpio-buttons.py         # Button testing script
docs/gpio-buttons.md         # This documentation
```

## Configuration Summary

**Minimal setup** in config.py:
```python
enable_gpio_buttons = True
gpio_program_button = board.D26
gpio_startstop_button = board.D19
```

**Hardware connections**:
- Program button: GPIO26 to GND
- Start/stop button: GPIO19 to GND
- Pull-up resistors: 10kΩ from each GPIO to 3.3V

This provides intuitive physical control while maintaining all existing safety features and web interface functionality.