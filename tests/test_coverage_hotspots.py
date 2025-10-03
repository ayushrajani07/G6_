import pathlib, textwrap, json, sys, os
from scripts.coverage_hotspots import parse_cobertura, ModuleCov, main as hotspots_main

def _write_xml(tmp_path, content: str) -> str:
    p = tmp_path / 'coverage.xml'
    p.write_text(content, encoding='utf-8')
    return str(p)

SAMPLE_XML = """<?xml version='1.0'?>
<coverage lines-valid='10' lines-covered='4' line-rate='0.4' branch-rate='0' timestamp='0' version='5.0'>
  <packages>
    <package name='pkg'>
      <classes>
        <class name='modA' filename='src/modA.py' line-rate='0.2'>
          <lines>
            <line number='1' hits='0'/>
            <line number='2' hits='0'/>
            <line number='3' hits='1'/>
            <line number='4' hits='0'/>
            <line number='5' hits='0'/>
          </lines>
        </class>
        <class name='modB' filename='src/modB.py' line-rate='0.6'>
          <lines>
            <line number='1' hits='1'/>
            <line number='2' hits='1'/>
            <line number='3' hits='1'/>
            <line number='4' hits='0'/>
            <line number='5' hits='0'/>
          </lines>
        </class>
        <class name='test_mod' filename='tests/test_something.py' line-rate='1.0'>
          <lines>
            <line number='1' hits='1'/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

def test_parse_and_ranking(tmp_path):
    xml_path = _write_xml(tmp_path, SAMPLE_XML)
    mods = parse_cobertura(xml_path, prefix='src/', exclude=['tests'])
    # Expect two modules
    assert len(mods) == 2
    # Validate ordering by risk (modA has more misses)
    mods.sort(key=lambda m: (-m.risk, m.coverage_pct))
    assert mods[0].name.endswith('modA.py')
    assert mods[0].lines_uncovered > mods[1].lines_uncovered


def test_cli_json_output(tmp_path, capsys):
    xml_path = _write_xml(tmp_path, SAMPLE_XML)
    # Invoke CLI main with JSON output and top=1
    # Lower min-lines to include 5-line sample modules (default 10 would filter them out)
    exit_code = hotspots_main(['--xml', xml_path, '--json', '--top', '1', '--min-lines', '1'])
    assert exit_code == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert 'modules' in payload and len(payload['modules']) == 1
    m0 = payload['modules'][0]
    assert m0['file'].endswith('modA.py') or m0['file'].endswith('modB.py')
    assert 'risk' in m0 and m0['risk'] >= 0


def test_baseline_json_delta(tmp_path, capsys):
  # Prepare initial baseline JSON using sample XML
  xml_path = _write_xml(tmp_path, SAMPLE_XML)
  code1 = hotspots_main(['--xml', xml_path, '--json', '--min-lines', '1'])
  assert code1 == 0
  baseline_json = capsys.readouterr().out
  baseline_path = tmp_path / 'baseline.json'
  baseline_path.write_text(baseline_json, encoding='utf-8')
  # Modify XML to change coverage (simulate improvement: convert one miss to hit in modA)
  improved_xml = SAMPLE_XML.replace("<line number='2' hits='0'/>", "<line number='2' hits='1'/>")
  xml_path2 = _write_xml(tmp_path, improved_xml)
  code2 = hotspots_main(['--xml', xml_path2, '--json', '--baseline', str(baseline_path), '--min-lines', '1'])
  assert code2 == 0
  new_payload = json.loads(capsys.readouterr().out)
  assert 'modules' in new_payload
  # Ensure at least one module has baseline_risk and risk_delta fields
  assert any('baseline_risk' in m and 'risk_delta' in m for m in new_payload['modules'])
  # risk_delta should be negative (improvement) for modA after increasing hits
  modA_entries = [m for m in new_payload['modules'] if m['file'].endswith('modA.py') and 'risk_delta' in m]
  if modA_entries:
    assert modA_entries[0]['risk_delta'] <= 0


def test_baseline_table_delta(tmp_path, capsys):
  xml_path = _write_xml(tmp_path, SAMPLE_XML)
  # produce baseline
  code_a = hotspots_main(['--xml', xml_path, '--json', '--min-lines', '1'])
  assert code_a == 0
  baseline_path = tmp_path / 'b.json'
  baseline_path.write_text(capsys.readouterr().out, encoding='utf-8')
  # second run (table mode) referencing baseline
  code_b = hotspots_main(['--xml', xml_path, '--baseline', str(baseline_path), '--min-lines', '1', '--top', '2'])
  assert code_b == 0
  out_table = capsys.readouterr().out
  # Header should contain ΔRisk
  assert 'ΔRisk' in out_table


def test_size_filters(tmp_path):
    # Create XML with a tiny module that should be excluded by min-lines (set via CLI)
    tiny_xml = """<?xml version='1.0'?><coverage><packages><package><classes>
    <class name='tiny' filename='src/tiny.py' line-rate='1.0'><lines>
      <line number='1' hits='1'/>
    </lines></class>
    <class name='big' filename='src/big.py' line-rate='0.0'><lines>
      <line number='1' hits='0'/>
      <line number='2' hits='0'/>
      <line number='3' hits='0'/>
      <line number='4' hits='0'/>
      <line number='5' hits='0'/>
      <line number='6' hits='0'/>
    </lines></class>
    </classes></package></packages></coverage>"""
    xml_path = _write_xml(tmp_path, tiny_xml)
    # min-lines default 10 filters both; override to 1 to include then ensure parse works
    mods_all = parse_cobertura(xml_path, prefix='src/', exclude=[])
    assert any(m.name.endswith('tiny.py') for m in mods_all)
    # Use CLI with min-lines 5 should include big but exclude tiny
    from scripts.coverage_hotspots import main as cli_main
    code = cli_main(['--xml', xml_path, '--prefix', 'src/', '--min-lines', '5', '--json'])
    assert code == 0

