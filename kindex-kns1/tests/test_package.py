import json
from pathlib import Path
import httpx,pytest
from kindex.cli import main
from kindex.providers import OpenAIEmbeddingProvider,ProviderError

def test_cli(tmp_path,capsys):
    db=str(tmp_path/'i.sqlite');sample=str(Path(__file__).parents[1]/'examples/snapshot.json')
    assert main(['build',sample,'--db',db])==0
    assert json.loads(capsys.readouterr().out)['nodes']==3
    assert main(['search','demo-v1','导出','--db',db])==0
    assert json.loads(capsys.readouterr().out)[0]['id']=='SOP.export'
    assert main(['relatives','demo-v1','SOP.export','--db',db])==0
    assert main(['strategies'])==0

def test_cli_embeddings_requires_explicit_config(tmp_path,monkeypatch):
    monkeypatch.delenv('KINDEX_EMBEDDING_ENDPOINT',raising=False)
    assert main(['search','v1','query','--db',str(tmp_path/'x.sqlite'),'--vectors'])==2

def test_http_embeddings_sorted_and_metered_without_credentials_in_identity():
    def respond(request):
        assert json.loads(request.content)['input']==['a','b']
        return httpx.Response(200,json={'data':[{'index':1,'embedding':[0,1]},{'index':0,'embedding':[1,0]}],'usage':{'total_tokens':2}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        p=OpenAIEmbeddingProvider('https://example.invalid/embeddings','demo','test-secret',client=client)
        assert p.embed(['a','b'])==[[1,0],[0,1]] and p.last_usage=={'total_tokens':2}
        assert 'test-secret' not in p.vector_identity()

@pytest.mark.parametrize('kind',['timeout','http','count','dimension','zero'])
def test_remote_failure_no_automatic_retry(kind):
    seen=[]
    def respond(r):
        seen.append(r)
        if kind=='timeout':raise httpx.ReadTimeout('details',request=r)
        if kind=='http':return httpx.Response(429)
        values={'count':[{'index':1,'embedding':[1,0]}], 'dimension':[{'index':0,'embedding':[1,0]},{'index':1,'embedding':[1]}], 'zero':[{'index':0,'embedding':[0,0]},{'index':1,'embedding':[0,0]}]}
        return httpx.Response(200,json={'data':values[kind]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        p=OpenAIEmbeddingProvider('https://example.invalid/embeddings','demo','test-secret',client=client)
        with pytest.raises(ProviderError):p.embed(['a','b'])
        assert len(seen)==1 and p.last_usage is None
