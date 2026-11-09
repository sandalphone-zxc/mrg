import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from kdiscovery.kd_s2_format import digest
ROOT=Path(__file__).resolve().parents[1]
COMMIT="a"*40

def port(key, state='draft'):
    return dict(key=key, name=key, meaning='a single document', necessity='required', granularity='single', state=state)


class FakeAPI:
    def __init__(self, files=None):
        self.files = files or {'README': b'Prepare and deliver documents.\nA document can be draft or complete.\n'}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if 'api.github.com' in url:
            return SimpleNamespace(json=lambda: {'tree': [{'path': p, 'type': 'blob', 'size': len(v)} for p, v in self.files.items()], 'truncated': False})
        path = url.split('/' + COMMIT + '/', 1)[1]
        return SimpleNamespace(content=self.files[path])


@pytest.fixture
def ws(tmp_path):
    (tmp_path / 'mrg.format.json').write_bytes((ROOT / 'mrg.format.json').read_bytes())
    return tmp_path
