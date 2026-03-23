"""Tests for clarion.cancellation — layer 0."""

from __future__ import annotations

import pytest

from clarion.cancellation import CancellationError, CancellationToken


def test_token_starts_uncancelled():
    token = CancellationToken()
    assert token.cancelled is False


def test_abort_sets_cancelled():
    token = CancellationToken()
    token.abort()
    assert token.cancelled is True


def test_check_does_nothing_when_not_cancelled():
    token = CancellationToken()
    token.check()  # should not raise


def test_check_raises_when_cancelled():
    token = CancellationToken()
    token.abort()
    with pytest.raises(CancellationError, match="Operation cancelled"):
        token.check()


def test_cancellation_error_is_raisable():
    with pytest.raises(CancellationError):
        raise CancellationError("test")
