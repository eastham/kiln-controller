#!/usr/bin/env python

"""
SPI utilities for coordinating access between multiple SPI devices
"""

import threading
import logging
from contextlib import contextmanager

log = logging.getLogger(__name__)

# Global SPI lock - initialized by main application
_spi_lock = None

def init_spi_lock():
    """Initialize the global SPI lock. Call this once from main application."""
    global _spi_lock
    _spi_lock = threading.RLock()
    log.info("SPI lock initialized")

@contextmanager
def spi_lock():
    """
    Context manager for SPI bus access. Use this to ensure exclusive SPI access:

    with spi_lock():
        # SPI operations here
        temp = thermocouple.temperature
    """
    if _spi_lock is None:
        log.warning("SPI lock not initialized - operations may conflict")
        yield
        return

#    log.debug("Acquiring SPI lock")
    with _spi_lock:
#        log.debug("SPI lock acquired")
        yield
#    log.debug("SPI lock released")

def is_spi_lock_initialized():
    """Check if SPI lock has been initialized"""
    return _spi_lock is not None