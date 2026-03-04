"""Pytest configuration — ensures tests run under Python 3.11."""
import sys
import pytest


def pytest_configure(config):
    """Warn if not running under Python 3.11."""
    major, minor = sys.version_info[:2]
    if (major, minor) != (3, 11):
        print(f"\nWARNING: Running under Python {major}.{minor}, expected 3.11")