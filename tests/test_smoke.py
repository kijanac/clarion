"""Smoke test — verifies that the clarion package is importable."""

import clarion


def test_version():
    assert clarion.__version__ == "0.1.0"
