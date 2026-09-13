"""Read-only access to ppa-eda-agent's recorded physical-design artifacts.

No sibling code is executed and no run is launched. File lists are lightweight;
geometry is returned only for the explicitly selected candidate.
"""
import json
import os
from pathlib import Path


def root():
    return Path(os.environ.get('PPA_EDA_ROOT', Path(__file__).resolve().parents[2] / 'ppa-eda-agent')).resolve()


def _case(name):
    if not name or Path(name).name != name or not name.endswith('.json'):
        raise ValueError('Invalid case file name')
    directory = (root() / 'reference-db' / 'cases').resolve()
    path = directory / name
    if path.is_symlink() or path.resolve().parent != directory:
        raise ValueError('Case must belong to the reference store')
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Case exceeds the 64 MiB read limit')
    return json.loads(path.read_text())


def list_cases():
    directory = root() / 'reference-db' / 'cases'
    if not directory.is_dir():
        return {'available': False, 'source': str(directory), 'cases': []}
    return {'available': True, 'source': str(directory), 'cases': [
        {'file': p.name, 'bytes': p.stat().st_size}
        for p in sorted(directory.glob('*.json'), reverse=True) if not p.is_symlink()
    ]}


def case_summary(name):
    data = _case(name)
    candidates = []
    for i, iteration in enumerate(data.get('iterations', [])):
        for result in iteration.get('results', []):
            layout = result.get('layout') or {}
            candidates.append({'iteration': i, 'tag': result.get('tag'),
                'cells': len(layout.get('cells', [])), 'nets': len(layout.get('nets', [])),
                'pdk': result.get('pdk'), 'verdict': result.get('verdict'),
                'error': result.get('error'), 'has_geometry': bool(layout.get('cells') or layout.get('nets'))})
    return {'file': name, 'design': data.get('design'), 'date': data.get('date'),
            'outcome': data.get('outcome'), 'winner_tag': data.get('winner_tag'), 'candidates': candidates}


def candidate(name, iteration, tag):
    data = _case(name)
    iterations = data.get('iterations', [])
    if iteration < 0 or iteration >= len(iterations):
        raise ValueError('Unknown iteration')
    for result in iterations[iteration].get('results', []):
        if result.get('tag') == tag:
            return {'file': name, 'design': data.get('design'), 'date': data.get('date'),
                    'tag': tag, 'iteration': iteration, 'layout': result.get('layout'),
                    'verdict': result.get('verdict'), 'pdk': result.get('pdk'),
                    'source': 'ppa-eda-agent / reference-db (recorded DEF/LEF geometry)',
                    'pointers': result.get('data_pointers'), 'run_dir': result.get('run_dir')}
    raise ValueError('Unknown candidate')
