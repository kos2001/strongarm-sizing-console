import json
import pytest
import physical_reference as ref


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('PPA_EDA_ROOT', str(tmp_path))
    cases = tmp_path / 'reference-db' / 'cases'
    cases.mkdir(parents=True)
    data = {'design': 'counter', 'date': '2026-09-13', 'iterations': [
        {'results': [{'tag': 'same', 'layout': {'die': [0, 0, 10, 10], 'cells': [{'inst': 'real'}], 'nets': []},
                      'verdict': {'passed': False, 'signoff_checks': [{'key': 'lvs', 'count': None}]}}]},
        {'results': [{'tag': 'same', 'layout': None}]}]}
    (cases / 'run.json').write_text(json.dumps(data))
    return cases


def test_summary_omits_geometry_and_preserves_unverified_checks(store):
    summary = ref.case_summary('run.json')
    assert summary['candidates'][0]['cells'] == 1
    assert 'layout' not in summary['candidates'][0]
    assert summary['candidates'][0]['verdict']['signoff_checks'][0]['count'] is None
    assert ref.list_cases()['cases'][0]['file'] == 'run.json'


def test_candidate_identity_includes_iteration(store):
    assert ref.candidate('run.json', 0, 'same')['layout']['cells'] == [{'inst': 'real'}]
    assert ref.candidate('run.json', 1, 'same')['layout'] is None
    with pytest.raises(ValueError):
        ref.candidate('run.json', -1, 'same')
    with pytest.raises(ValueError):
        ref.candidate('run.json', 0, 'unknown')


def test_only_case_files_inside_store_can_be_read(store, tmp_path):
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    (store / 'linked.json').symlink_to(outside)
    for name in ['../../outside.json', str(outside), 'linked.json']:
        with pytest.raises(ValueError):
            ref.case_summary(name)
    assert not any(item['file'] == 'linked.json' for item in ref.list_cases()['cases'])


def test_missing_store_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv('PPA_EDA_ROOT', str(tmp_path / 'missing'))
    assert ref.list_cases()['available'] is False
