"""Paths owned by this checkout; no companion or Earth2Road installation required."""
from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / 'out'
