import os
import pytest

from src.collectors.env_adapter import get_bool, get_int, get_float, get_str, get_csv


def test_get_bool_truthy_falsey(monkeypatch: pytest.MonkeyPatch) -> None:
    # Missing -> default
    assert get_bool('G6_TEST_BOOL_X', False) is False
    assert get_bool('G6_TEST_BOOL_X', True) is True

    # Truthy values
    for v in ['1','true','TRUE','Yes','on','y','Y']:
        monkeypatch.setenv('G6_TEST_BOOL_T', v)
        assert get_bool('G6_TEST_BOOL_T', False) is True

    # Falsy/other values
    for v in ['0','false','no','off','', '  ', 'random']:
        monkeypatch.setenv('G6_TEST_BOOL_F', v)
        assert get_bool('G6_TEST_BOOL_F', True) is (v.strip().lower() in {'1','true','yes','on','y'})


def test_get_int_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_int('G6_TEST_INT_MISSING', 42) == 42
    monkeypatch.setenv('G6_TEST_INT', '10')
    assert get_int('G6_TEST_INT', 0) == 10
    # invalid -> default
    monkeypatch.setenv('G6_TEST_INT', 'not-an-int')
    assert get_int('G6_TEST_INT', 7) == 7


def test_get_float_and_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_float('G6_TEST_FLOAT_MISSING', 3.14) == 3.14
    monkeypatch.setenv('G6_TEST_FLOAT', '2.5')
    assert abs(get_float('G6_TEST_FLOAT', 0.0) - 2.5) < 1e-9
    # invalid -> default
    monkeypatch.setenv('G6_TEST_FLOAT', 'oops')
    assert get_float('G6_TEST_FLOAT', 1.5) == 1.5


def test_get_str_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_str('G6_TEST_STR_MISSING', 'abc') == 'abc'
    monkeypatch.setenv('G6_TEST_STR', ' hello ')
    assert get_str('G6_TEST_STR', '') == ' hello '


def test_get_csv_parse_and_transform(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_csv('G6_TEST_CSV_MISSING', ['a','b']) == ['a','b']
    monkeypatch.setenv('G6_TEST_CSV', 'nifty, banknifty , , sensex ')
    assert get_csv('G6_TEST_CSV', None) == ['nifty','banknifty','sensex']
    assert get_csv('G6_TEST_CSV', None, transform=str.upper) == ['NIFTY','BANKNIFTY','SENSEX']
