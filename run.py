#!/usr/bin/env python3
"""Backwards-compatible entry point. Prefer: pip install . && recipro"""
import sys
from recipro.cli import main

sys.exit(main())
