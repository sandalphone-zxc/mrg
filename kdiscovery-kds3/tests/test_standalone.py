import json
from importlib.resources import files
from pathlib import Path
import httpx
import pytest
from kdiscovery import KDiscovery, GraphDiscovery, initialize_workspace
from kdiscovery.cli import main
from kdiscovery.providers import OpenAICompatibleProvider, OutputError, ProviderError, JSON_PREFIX

def test_public_registry_and_schema(tmp_path):
    assert [d['strategy'] for d in KDiscovery.describe()] == ['KD-S-3']
    assert isinstance(KDiscovery.create('github', 'KD-S-3', None, tmp_path), GraphDiscovery)
    with pytest.raises(TypeError): KDiscovery()
    root = initialize_workspace(tmp_path)
    expected = files('kdiscovery').joinpath('resources/mrg.format.json').read_bytes()
    assert (root/'mrg.format.json').read_bytes() == expected
    assert (Path(__file__).parents[1]/'mrg.format.json').read_bytes() == expected
    (root/'mrg.format.json').write_text('{}')
    with pytest.raises(ValueError): initialize_workspace(root)

def test_cli_never_mines_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv('KDISCOVERY_API_KEY', raising=False)
    assert main(['strategies']) == 0
    assert main(['mine', '--workspace', str(tmp_path), '--repo', 'demo/example',
                 '--commit', 'a'*40, '--run-id', 'test']) == 2

def test_provider_protocol_usage_and_no_key_persistence(tmp_path):
    def respond(request):
        data=json.loads(request.content)
        assert data['temperature']==0 and data['max_tokens']==12288
        assert data['messages'][0]['content']==JSON_PREFIX+'prompt'
        assert data['thinking']=={'type':'enabled'} and data['reasoning_effort']=='low'
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],
                                      'usage':{'prompt_tokens':13,'completion_tokens':7,'total_tokens':20}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        path=tmp_path/'usage.json'
        p=OpenAICompatibleProvider('https://example.invalid/v1/chat/completions','deepseek-v4-pro','test-secret',path,client=client)
        assert p.json('prompt',{},reasoning_effort='low')=={'ok':True}
        raw=path.read_text();assert 'test-secret' not in raw
        assert json.loads(raw)[0]['usage']['total_tokens']==20

@pytest.mark.parametrize('kind', ['timeout','http','truncated','invalid'])
def test_provider_errors_account_once_without_retry(tmp_path,kind):
    seen=[]
    def respond(request):
        seen.append(request)
        if kind=='timeout':raise httpx.ReadTimeout('sensitive transport details',request=request)
        if kind=='http':return httpx.Response(429,text='sensitive service details')
        if kind=='invalid':return httpx.Response(200,json={'unexpected':'envelope'})
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"features":['},'finish_reason':'length'}],
                                      'usage':{'total_tokens':9}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        path=tmp_path/'usage.json'
        p=OpenAICompatibleProvider('https://example.invalid/v1/chat/completions','model','test-secret',path,client=client)
        with pytest.raises((ProviderError,OutputError)):
            p.json('prompt',{},capture_partial=True)
        assert len(seen)==1
        row=json.loads(path.read_text())[0]
        assert row['usage']==({'total_tokens':9} if kind=='truncated' else None)
        assert row['status']==('result_unknown' if kind=='timeout' else 'requested' if kind=='http' else 'received')

def test_reject_embedded_endpoint_credentials(tmp_path):
    for url in ['http://example.invalid', 'https://user:secret@example.invalid', 'https://example.invalid?key=secret']:
        with pytest.raises(ValueError):OpenAICompatibleProvider(url,'model','secret',tmp_path/'u.json')

def test_packaged_modules_have_no_host_app_imports():
    import ast
    root=Path(__file__).parents[1]/'src/kdiscovery'
    for p in root.glob('*.py'):
        for n in ast.walk(ast.parse(p.read_text(encoding='utf8'))):
            if isinstance(n,ast.ImportFrom):assert not (n.module or '').startswith('app.')

def test_run_lock_rejects_competition_and_releases(tmp_path):
    from kdiscovery.api import exclusive_run
    with exclusive_run(tmp_path):
        with pytest.raises(RuntimeError):
            with exclusive_run(tmp_path):pass
    with exclusive_run(tmp_path):pass
