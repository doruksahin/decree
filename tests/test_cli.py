"""Tests for decree.cli — entry point."""
import subprocess
import sys

def test_help():
    r = subprocess.run([sys.executable, "-m", "decree.cli", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "new" in r.stdout
    assert "lint" in r.stdout

def test_new_help():
    r = subprocess.run([sys.executable, "-m", "decree.cli", "new", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "title" in r.stdout.lower()
