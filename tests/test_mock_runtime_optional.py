import json
import pytest

pytestmark = pytest.mark.optional


def test_single_mock_cycle(run_mock_cycle):
    data = run_mock_cycle(cycles=1, interval=2)
    assert data.get('timestamp','').endswith('Z')
    assert data.get('cycle') in (0,1)


def test_multi_cycle_progress(run_mock_cycle):
    data = run_mock_cycle(cycles=3, interval=2)
    assert data.get('cycle') >= 2


@pytest.mark.slow
def test_multi_cycle_slower(run_mock_cycle):
    data = run_mock_cycle(cycles=5, interval=2)
    assert data.get('cycle') >= 4
