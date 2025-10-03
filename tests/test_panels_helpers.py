from src.panels.helpers import compute_status_and_reason


def test_panels_style_ok_and_warn_and_error():
    # OK when success >= 95
    st, reason = compute_status_and_reason(success_pct=97, legs=10, style='panels')
    assert st == 'OK' and (reason is None or 'success' in reason or reason == '')
    # WARN when 80 <= success < 95
    st, reason = compute_status_and_reason(success_pct=90, legs=10, style='panels')
    assert st == 'WARN'
    assert reason in (f'success 90%', None) or 'success' in (reason or '')
    # ERROR when success < 80
    st, reason = compute_status_and_reason(success_pct=70, legs=10, style='panels')
    assert st == 'ERROR'
    assert reason == 'low success 70%'
    # No legs reason
    st, reason = compute_status_and_reason(success_pct=70, legs=0, style='panels')
    assert st == 'ERROR'
    assert reason == 'no legs this cycle'


def test_web_style_status_and_reasons():
    # bad when no success
    st, reason = compute_status_and_reason(success_pct=None, legs=5, style='web')
    assert st == 'bad'
    assert reason == 'no success metric'
    # warn on success < 92
    st, reason = compute_status_and_reason(success_pct=90, legs=5, style='web')
    assert st == 'warn'
    assert reason == 'success 90%'
    # ok on high success and legs present
    st, reason = compute_status_and_reason(success_pct=98, legs=12, style='web')
    assert st == 'ok'
    assert reason is None
    # bad on zero legs
    st, reason = compute_status_and_reason(success_pct=98, legs=0, style='web')
    assert st == 'bad'
    assert reason == 'no legs this cycle'
    # err_recent influences warn
    st, reason = compute_status_and_reason(success_pct=98, legs=10, style='web', err_recent=True, err_type='timeout')
    assert st == 'warn'
    assert reason == 'error: timeout'
