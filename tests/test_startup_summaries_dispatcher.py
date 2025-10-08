import logging
from io import StringIO


def test_register_or_note_summary_idempotent():
    from src.observability import startup_summaries as ss  # type: ignore
    # Isolate registry state
    ss._REGISTRY.clear(); ss._EMITTED.clear(); ss._JSON_FIELD_HASHES.clear(); ss._COMPOSITE_EMITTED = False  # type: ignore
    ss.register_or_note_summary('foo', emitted=False)
    ss.register_or_note_summary('foo', emitted=True)  # second call should not duplicate registry entry
    names = [n for n,_ in ss._REGISTRY]  # type: ignore
    assert names.count('foo') == 1
    assert ss._EMITTED['foo'] is True


def test_emit_and_register_summary_runs_once():
    from src.observability import startup_summaries as ss  # type: ignore
    ss._REGISTRY.clear(); ss._EMITTED.clear(); ss._JSON_FIELD_HASHES.clear(); ss._COMPOSITE_EMITTED = False  # type: ignore
    calls = {'cnt': 0}
    def _emitter():
        calls['cnt'] += 1
        logging.getLogger('dummy').info('dummy.summary example=1')
        return True
    ran_first = ss.emit_and_register_summary('dummy', _emitter)
    ran_second = ss.emit_and_register_summary('dummy', _emitter)
    assert ran_first is True
    assert ran_second is False  # skipped second time
    assert calls['cnt'] == 1
    assert ss._EMITTED['dummy'] is True
    # Dispatcher should not re-run emitter
    stream = StringIO(); handler = logging.StreamHandler(stream)
    logging.getLogger('dummy').addHandler(handler)
    logging.getLogger('dummy').setLevel(logging.INFO)
    ss.emit_all_summaries()
    out = stream.getvalue()
    assert out.count('dummy.summary') == 0  # emitter not re-invoked by dispatcher


def test_emit_and_register_summary_composite_hash():
    from src.observability import startup_summaries as ss  # type: ignore
    ss._REGISTRY.clear(); ss._EMITTED.clear(); ss._JSON_FIELD_HASHES.clear(); ss._COMPOSITE_EMITTED = False  # type: ignore
    # Provide emitter that also emits JSON via summary_json helper
    import json
    def _emitter():
        from src.utils.summary_json import emit_summary_json  # type: ignore
        emit_summary_json('helper.test', [('alpha', 1), ('beta', 2)], logger_override=logging.getLogger('test.helper'))
        return True
    ss.emit_and_register_summary('helper.test', _emitter)
    stream = StringIO(); handler = logging.StreamHandler(stream)
    dlog = logging.getLogger('src.observability.startup_summaries'); dlog.addHandler(handler); dlog.setLevel(logging.INFO)
    ss.emit_all_summaries()
    out = stream.getvalue()
    assert 'startup.summaries.hash' in out
    # Ensure hash count reflects exactly one JSON summary hash
    assert 'count=1' in out or 'count=1 ' in out
