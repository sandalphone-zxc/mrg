import copy,json
from pathlib import Path
import pytest
from fixtures import ws,FakeAPI,COMMIT
from test_kd_s3 import Model,fake_graph
from test_v2_contracts import fixture
from kdiscovery.kd_s3 import incremental,merge_reviewed,GraphDiscovery
from kdiscovery.kd_s3_contracts import overview_prefix,normalize_delta,clean_overview,obtain_overview
from kdiscovery.kd_s3_review import normalize_verdicts
from kdiscovery.kd_s3_requirements import document_units,feature_sources


def test_latest_local_operation_cannot_replace_business_goal():
    base,_=fixture();extra=copy.deepcopy(base)
    extra['mrg']['SOP'][0].update(name='Local helper',purpose='Just one operation')
    merged=merge_reviewed(base,extra)
    assert merged['mrg']['SOP'][0]['purpose']==base['mrg']['SOP'][0]['purpose']


def test_incomplete_boundary_change_preserves_other_delta():
    base,_=fixture()
    raw=dict(scope_extension=dict(name='Local',purpose='Small action'),steps=[],evidence=[],gaps=[],contract_additions=[])
    value=incremental(raw,base)
    assert value['sop']['purpose']==base['mrg']['SOP'][0]['purpose']
    assert len(value['gaps'])==2


def test_explicit_boundary_change_requires_targeted_check():
    base,_=fixture();old=base['mrg']['SOP'][0]['purpose']
    raw=dict(scope_extension=dict(name='Extended goal',purpose='Includes old delivery and new branch',previous_goal=old,reason='New visible branch'),evidence=[dict(target='sop',field='purpose',path='app.py',line=1)])
    value=incremental(raw,base)
    assert value['boundary_change']['previous_goal']==old
    assert value['uncertainties'][0]['target']=='sop'


def test_partial_json_keeps_complete_objects_only():
    text='{"project":{"name":"Demo"},"features":[{"key":"a","name":"A","goal":"Deliver A"},{"key":"b","name":"unfinished'
    value=overview_prefix(text)
    assert value['project']['name']=='Demo' and len(value['features'])==1
    assert overview_prefix('{"project":{"name":"unfinished')=={}


def test_reverse_doc_mapping_reaches_extraction():
    proof={'README':dict(sha256='x',lines=[dict(line=1,text='Deliver orders')])};units=document_units(proof)
    overview=clean_overview(dict(features=[dict(key='orders',name='Orders',goal='Deliver orders')],document_coverage=[dict(unit_id=units[0]['id'],feature_keys=['orders'])]),units)
    assert feature_sources(overview['features'][0],units,proof)==proof


def test_other_goal_step_is_quarantined_without_losing_siblings():
    raw={'steps':[dict(key='a',name='A',ownership='same'),dict(key='b',name='B',ownership='other',ownership_reason='different final delivery')],
         'links':[dict(source='a',target='b')],'output_bindings':[dict(step='b')], 'evidence':[dict(target='b',field='purpose')]}
    result=normalize_delta(raw)
    assert [s['key'] for s in result['steps']]==['a']
    assert not result['links'] and not result['output_bindings'] and not result['evidence'] and result['gaps']


def test_review_protocol_error_only_affects_that_claim():
    base,proof=fixture();batch=[dict(id='a'),dict(id='b'),dict(id='c')]
    good,bad,fixed=normalize_verdicts(dict(accepted=['a',{'id':'b'}],unknown=['b'],corrections=[dict(id='absent',path='x',line=99)]),batch,base,proof)
    assert good==['a'] and {x['id'] for x in bad}=={'b','c'} and fixed==[]


def test_overview_repair_once_and_success_not_repeated(ws):
    class Truncated(ValueError):pass
    class Calls:
        count=0
        def call(self,task,prompt,data):
            self.count+=1
            if self.count==1:
                e=Truncated('truncated');e.response_content='{"project":{"name":"Demo"},"features":[{"key":"a","name":"A","goal":"Deliver A"},'
                raise e
            return dict(project=dict(name='Demo'),features=[dict(key='b',name='B',goal='Deliver B')])
    c=Calls();state={};data=dict(document_units=[]);path=ws/'state.json'
    result=obtain_overview(c,'',data,state,path)
    assert {f['key'] for f in result['features']}=={'a','b'} and c.count==2
    assert obtain_overview(c,'',data,state,path)==result and c.count==2


def test_overview_failure_keeps_code_discovery_available(ws,monkeypatch):
    monkeypatch.setattr('kdiscovery.kd_s3.build',fake_graph)
    class PartialModel(Model):
        def json_background(self,p,d):
            if 'project_id' in d:raise ValueError('overview local output failure')
            return super().json_background(p,d)
    model=PartialModel();api=FakeAPI({'README':b'Deliver documents.','app.py':b'def deliver(document):\n    save(document)\n    return document\n'})
    result=GraphDiscovery(model,ws,api).extract({'repo':'demo/example','commit':COMMIT},{},{},'recover')
    folder=Path(result['folder']);m=json.loads((folder/'mrg.json').read_text(encoding='utf8'))
    assert m['SOP'] and m['OMN']
    assert json.loads((folder/'round-1.json').read_text(encoding='utf8'))['requests']<=24
