import copy,json
from pathlib import Path
import pytest
from kindex import KIndex,HierarchicalIndex,SQLiteStore,ProviderError
from kindex.retrieval import tokens

@pytest.fixture
def snapshot():return json.loads((Path(__file__).parents[1]/'examples/snapshot.json').read_text(encoding='utf8'))

@pytest.fixture
def store(tmp_path):return SQLiteStore(tmp_path/'index.sqlite')

class Embeddings:
    def __init__(self,identity='fake-v1'):self.calls=[];self.identity=identity
    def status(self):return {'embedding_configured':True}
    def vector_identity(self):return self.identity
    def embed(self,texts):self.calls.append(list(texts));return [[1.,0.] for _ in texts]

def test_registry():
    assert [v['strategy'] for v in KIndex.describe()]==['KN-S-1']
    with pytest.raises(TypeError):KIndex()
    with pytest.raises(ValueError):KIndex.create('github','unknown')

def test_build_search_and_hierarchy(store,snapshot):
    index=KIndex.create('github','KN-S-1',store)
    first=index.build(snapshot);assert first['nodes']==3 and first['keyword_ready'] and not first['vectors_ready']
    assert index.build(snapshot)==first
    result=index.search(snapshot['id'],'导出报告')
    assert result[0]['id']=='SOP.export' and 'match_evidence' in result[0]
    assert index.search(snapshot['id'],'export')[0]['id']=='SOP.export'
    assert index.search(snapshot['id'],'渲染',include_units=True)[0]['kind']=='unit'
    assert index.search(snapshot['id'],'渲染')==[]
    assert index.relatives(snapshot['id'],'UNIT.render')[-1]['id']=='SOP.documents'
    assert [v['distance'] for v in index.relatives(snapshot['id'],'SOP.documents','children')]==[1,2]
    with pytest.raises(LookupError):index.relatives(snapshot['id'],'missing')
    with pytest.raises(ValueError):index.relatives(snapshot['id'],'SOP.export','invalid')

def test_filters(store,snapshot):
    index=HierarchicalIndex(store);index.build(snapshot)
    assert index.search(snapshot['id'],'报告',license_id='Apache-2.0')==[]
    assert index.search(snapshot['id'],'导出',require_code=True)[0]['id']=='SOP.export'
    assert index.search(snapshot['id'],'导出',min_completeness=3)[0]['id']=='SOP.export'
    assert index.search(snapshot['id'],'导出',max_specificity=0)==[]
    assert index.search(snapshot['id'],'" OR *')==[]
    assert index.search(snapshot['id'],'')==[]

def test_vectors_cache_new_snapshot_model_isolation_and_reopen(store,snapshot):
    provider=Embeddings();index=HierarchicalIndex(store,provider)
    assert index.build(snapshot)['embedded']==3
    assert index.build(snapshot)['embedded']==0
    other=copy.deepcopy(snapshot);other['id']='demo-v2'
    assert index.build(other)['reused']==3 and len(provider.calls)==1
    again=HierarchicalIndex(SQLiteStore(store.path),provider)
    assert again.build(other)['embedded']==0
    assert '语义相似' in again.search(other['id'],'unmatched')[0]['match_evidence']
    changed=Embeddings('fake-v2');assert HierarchicalIndex(store,changed).build(other)['embedded']==3

def test_changed_content_only_embeds_changed_document(store,snapshot):
    p=Embeddings();index=HierarchicalIndex(store,p);index.build(snapshot)
    changed=copy.deepcopy(snapshot);changed['id']='v2';changed['entities']['SOP.export']['goal']='Download printable results'
    assert index.build(changed)['embedded']==1 and len(p.calls[-1])==1
    assert index.search(snapshot['id'],'导出')[0]['goal']==snapshot['entities']['SOP.export']['goal']

def test_mutating_snapshot_id_is_rejected_including_metadata(store,snapshot):
    i=HierarchicalIndex(store);i.build(snapshot)
    changed=copy.deepcopy(snapshot);changed['projects']['demo']['license']='Other'
    with pytest.raises(ValueError,match='immutable'):i.build(changed)
    assert i.search(snapshot['id'],'导出')[0]['license']=='MIT'

@pytest.mark.parametrize('kind',['cycle','missing','multiple','unit_cycle','unit_missing','cross_owner'])
def test_invalid_ownership_fails_without_database_writes(store,snapshot,kind):
    if kind=='cycle':snapshot['entities']['SOP.export']['sub_sop_refs']=['SOP.documents']
    elif kind=='missing':snapshot['entities']['SOP.documents']['sub_sop_refs']=['missing']
    elif kind=='multiple':snapshot['projects']['demo']['mns']['SOP_refs'].append('SOP.export')
    elif kind=='unit_cycle':snapshot['trees']['demo']['nodes'][0]['parent']='UNIT.render'
    elif kind=='unit_missing':snapshot['trees']['demo']['nodes'][0]['parent']='missing'
    else:snapshot['projects']['other']=copy.deepcopy(snapshot['projects']['demo'])
    index=HierarchicalIndex(store)
    with pytest.raises(ValueError):index.build(snapshot)
    with store.connect() as db:assert db.execute('SELECT count(*) FROM kn_nodes').fetchone()[0]==0

@pytest.mark.parametrize('bad',[[],[[0,0]],[[float('nan'),1]],[[1,0],[1,0]]])
def test_invalid_embedding_keeps_keywords_without_publishing_vectors(store,snapshot,bad):
    class Bad(Embeddings):
        def embed(self,texts):return bad
    i=HierarchicalIndex(store,Bad())
    with pytest.raises(ValueError):i.build(snapshot)
    assert i.search(snapshot['id'],'导出',use_vectors=False)
    with store.connect() as db:assert db.execute('SELECT count(*) FROM kn_vectors').fetchone()[0]==0

def test_embedding_failure_falls_back_to_keywords(store,snapshot):
    class Failing(Embeddings):
        def embed(self,texts):raise ProviderError('offline')
    i=HierarchicalIndex(store);i.build(snapshot);i.providers=Failing()
    assert i.search(snapshot['id'],'导出')[0]['id']=='SOP.export'

def test_batch_cache_survives_failed_later_batch(store,snapshot):
    snapshot['trees']={};snapshot['entities']['SOP.documents']['sub_sop_refs']=[];snapshot['rows']={}
    for n in range(26):
        sid=f'SOP.child{n}';snapshot['entities'][sid]={'name':f'Function {n}','goal':f'Goal {n}'}
        snapshot['entities']['SOP.documents']['sub_sop_refs'].append(sid)
    class Partial(Embeddings):
        def embed(self,texts):
            if len(self.calls)==1:raise ProviderError('second batch unavailable')
            return super().embed(texts)
    p=Partial();i=HierarchicalIndex(store,p)
    with pytest.raises(ProviderError):i.build(snapshot)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM kn_vector_cache').fetchone()[0]==24
        assert db.execute('SELECT count(*) FROM kn_vectors').fetchone()[0]==0
    good=Embeddings();i.providers=good
    assert i.build(snapshot)['embedded']==3 and len(good.calls[0])==3

def test_original_algorithm_parity(tmp_path,snapshot):
    source=(Path(__file__).parent/'reference_kn_s1.py').read_text(encoding='utf8').replace('@KIndex.register','')
    namespace={'__name__':'kindex.reference','__package__':'kindex'};exec(compile(source,'reference_kn_s1.py','exec'),namespace)
    old=namespace['HierarchicalIndex'](SQLiteStore(tmp_path/'old.sqlite'),Embeddings())
    new=HierarchicalIndex(SQLiteStore(tmp_path/'new.sqlite'),Embeddings())
    assert old.documents(snapshot)==new.documents(snapshot)
    assert old.build(snapshot)==new.build(snapshot)
    for query in ['导出','export','渲染','unmatched']:
        for vectors in (False,True):
            assert old.search(snapshot['id'],query,include_units=True,use_vectors=vectors)==new.search(snapshot['id'],query,include_units=True,use_vectors=vectors)
    assert old.relatives(snapshot['id'],'SOP.export')==new.relatives(snapshot['id'],'SOP.export')

def test_tokenization():assert tokens('报告 EXPORT')==['export','报告']

@pytest.mark.parametrize('limit',[0,-1,1001,True,2.5])
def test_query_limit_contract(store,limit):
    with pytest.raises(ValueError):HierarchicalIndex(store).search('v1','query',limit=limit)

def test_raw_requirement_mrg_is_not_silently_converted(store):
    with pytest.raises(ValueError):HierarchicalIndex(store).build({'format':'mrg-requirements-v1','MNS':{},'SOP':[]})
