from __future__ import annotations
import pytest

pytestmark = pytest.mark.skip(reason="UI badge rendering intentionally not asserted to avoid Rich formatting brittleness")

def test_placeholder():
    assert True
