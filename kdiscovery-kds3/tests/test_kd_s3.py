import copy,json
from pathlib import Path
import pytest
from fixtures import ws,FakeAPI,COMMIT,port
from kdiscovery.kd_s2_format import digest,validate,definition
from kdiscovery.kd_s2_sources import atomic
from kdiscovery.kd_s2_report import verify
from kdiscovery.kd_s3 import GraphDiscovery,schedule
from kdiscovery.kd_s3_calls import Calls,ServicePause,PriorFailure
from kdiscovery.kd_s2 import BudgetPause
from kdiscovery.kd_s3_graph import vue_script

def test_vue_original_line_numbers():
    raw='<template>\n<div/>\n</template>\n<script setup lang="ts">\nfunction pay() { return 1; }\n</script>\n<style>h1{}</style>'
    value,has,ts=vue_script(raw)
    assert has and ts and value.splitlines()[4]=='function pay() { return 1; }'
    assert len(value.splitlines())==len(raw.splitlines()) and '<div' not in value

def test_calls_budget_resume_unknown_and_failure(ws):
    class Model:
        count=0
        def json_background(self,p,d):self.count+=1;return {'ok':True}
    identity={'format':'mrg-requirements-v1','strategy':'KD-S-3','rule_hash':'a','schema_hash':'b'};model=Model()
    c=Calls(model,ws,identity);c.call('first','prompt',{})
    Calls(model,ws,identity).call('first','prompt',{});assert model.count==1
    c=Calls(model,ws,identity);c.state['requests']=24;atomic(c.path,c.state)
    with pytest.raises(BudgetPause):c.call('next','prompt',{})
    c.state['calls'].append({'key':'unknown','status':'requested'});atomic(c.path,c.state)
    with pytest.raises(ServicePause):Calls(model,ws,identity)

def test_character_budget_before_model(ws):
    c=Calls(None,ws,{'format':'mrg-requirements-v1','schema_hash':'b'})
    with pytest.raises(BudgetPause):c.call('large','',{'sources':{'f':{'sha256':'a','lines':[{'line':1,'text':'x'*200001}]}}})
    assert c.state['requests']==0

def fake_graph(materials,workspace,note):
    materials.inventory();materials.read('README');materials.read('app.py')
    nodes=[{'id':'py:1','label':'METHOD','path':'app.py','NAME':'deliver','FULL_NAME':'kdiscovery.deliver','LINE_NUMBER':1,'LINE_NUMBER_END':3}]
    graph={'methods':nodes,'nodes':nodes,'edges':[],'omissions':[],'limits':['static only']}
    return graph,{'identity':{'tool':{'version':'fake'}},'nodes':1,'edges':0,'methods':1,'acquisition_seconds':0,'graph_seconds':0}

class Model:
    def __init__(self):self.calls=[]
    def json_background(self,p,data):
        self.calls.append(copy.deepcopy(data))
        if 'project_id' in data:return {'project':{'name':'Documents','goal':'Deliver documents','users':[],'scenarios':[]},
            'project_evidence':[{'field':'goal','path':'README','line':1}],
            'features':[{'key':'delivery','name':'Delivery','goal':'Deliver documents','locators':['app.py']}],
            'document_coverage':[{'unit_id':u['id'],'feature_keys':['delivery'],'status':'mapped','reason':'Document delivery'} for u in data.get('document_units',[])], 'gaps':[]}
        if 'claims' in data:return {'accepted':[c['id'] for c in data['claims']], 'rejected':[], 'unknown':[]}
        if 'feature' in data:
            return {'sop':{'name':'Delivery','purpose':'Deliver documents','inputs':[port('document')],'outputs':[port('delivered')]},
                'steps':[{'key':'save','name':'Save document','purpose':'Save document','actor':'system','inputs':[port('document')],'outputs':[port('delivered')],'rules':[]}],
                'output_bindings':[{'output_key':'delivered','step':'save','node_output_key':'delivered','meaning':'saved document'}],
                'evidence':[{'target':target,'field':field,'path':'app.py','line':2} for target in ('sop','save') for field in ('purpose','inputs/0','outputs/0')]+[{'target':'sop','field':'output_bindings/0','path':'app.py','line':2}],
                'implementations':[{'target':'save','path':'app.py','line':2,'symbol':'deliver'}]}
        return {'project_supported':True,'decisions':[{'sop_id':s['id'],'keep':True,'reason':'source supports'} for s in data['proposal']['mrg']['SOP']],
            'drop_facts':[],'drop_edges':[],'coverage':{'relation':'same','remaining':[]}}

def test_pipeline_preserves_ownership_sources_and_replays(ws,monkeypatch):
    monkeypatch.setattr('kdiscovery.kd_s3.build',fake_graph)
    api=FakeAPI({'README':b'Deliver documents.','app.py':b'def deliver(document):\n    save(document)\n    return document\n'})
    model=Model();strategy=GraphDiscovery(model,ws,api)
    a=strategy.extract({'repo':'demo/example','commit':COMMIT},{},{},'kds3')
    folder=Path(a['folder']);manifest=verify(folder);m=json.loads((folder/'mrg.json').read_text(encoding='utf8'))
    assert manifest['strategy']=='KD-S-3' and '/KD-S-3/' in folder.as_posix()
    assert len(m['SOP'])==1 and len(m['OMN'])==1 and m['OMN'][0]['sop_id']==m['SOP'][0]['id']
    assert m['SOP'][0]['output_bindings'][0]['node_id']==m['OMN'][0]['id']
    before=len(model.calls);strategy.extract({'repo':'demo/example','commit':COMMIT},{},{},'kds3');assert len(model.calls)==before
    validate(m,definition(ws)[0]);assert all(d['contract']['strategy']=='KD-S-3' for d in model.calls)

def test_graph_failure_never_calls_model(ws,monkeypatch):
    def fail(*args):raise RuntimeError('parse failure')
    monkeypatch.setattr('kdiscovery.kd_s3.build',fail);model=Model()
    with pytest.raises(RuntimeError):GraphDiscovery(model,ws,FakeAPI()).extract({'repo':'demo/example','commit':COMMIT},{},{},'failed')
    assert model.calls==[]

def test_schedule_includes_undocumented_code_and_groups_interfaces():
    nodes=[{'id':str(i),'NAME':str(i),'FULL_NAME':str(i),'path':p,'LINE_NUMBER':1,'LINE_NUMBER_END':2} for i,p in enumerate(['a.py','a.py','b.py'])]
    features,_=schedule({'features':[{'key':'a','name':'A','goal':'A','locators':['a.py']}]},{'methods':nodes},'demo/example')
    assert len(features)==2 and len(next(f for f in features if f['document_candidate'])['roots'])==2
    assert any(not f['document_candidate'] and f['locators']==['b.py'] for f in features)


def test_local_unsupported_step_does_not_drop_function(ws,monkeypatch):
    monkeypatch.setattr('kdiscovery.kd_s3.build',fake_graph)
    class RejectStep(Model):
        def json_background(self,p,d):
            out=super().json_background(p,d)
            if 'feature' in d:
                out['uncertainties']=[{'target':'save','field':'purpose','reason':'本片段无法确定保存操作是否实现交付'}]
            if 'claims' in d:
                rejected=[c['id'] for c in d['claims'] if c['kind']=='OMN' and c['field']=='purpose']
                out={'accepted':[c['id'] for c in d['claims'] if c['id'] not in rejected],'rejected':[{'id':i,'reason':'unsupported step'} for i in rejected],'unknown':[]}
            return out
    api=FakeAPI({'README':b'Deliver documents.','app.py':b'def deliver(document):\n    save(document)\n    return document\n'})
    result=GraphDiscovery(RejectStep(),ws,api).extract({'repo':'demo/example','commit':COMMIT},{},{},'drop')
    m=json.loads((Path(result['folder'])/'mrg.json').read_text(encoding='utf8'))
    assert len(m['SOP'])==1 and m['OMN']==[] and m['SOP'][0]['output_bindings']==[]

def test_relationship_failure_keeps_confirmed_functions_and_bounds_repair(ws):
    from kdiscovery.kd_s2_format import empty
    m=empty({'MNS':{'id':'MNS.test','name':'test'}})
    m['SOP']=[{'id':'SOP.a','name':'A'},{'id':'SOP.b','name':'B'}]
    result={'mrg':m,'evidence':[],'implementations':[]}
    state={'ledger':{'SOP.a':{'roots':['a']},'SOP.b':{'roots':['b']}},
        'accepted':{s:{'value':{'implementations':[]},'proof':{}} for s in ('SOP.a','SOP.b')},
        'relation_checks':[],'failures':[],'removed':[]}
    class Broken:
        n=0
        def remaining(self):return 24-self.n
        def call(self,*a):self.n+=1;raise ValueError('invalid JSON')
    for key in ('a','b'):
        state['accepted']['SOP.'+key]['value']['implementations']=[{'path':key+'.py','line':1,'symbol':key}]
    calls=Broken();graph={'edges':[{'source':'a','target':'b','label':'METHOD_CALL'}],
        'methods':[{'id':k,'label':'METHOD','path':k+'.py','NAME':k,'FULL_NAME':k+'.py::'+k,'LINE_NUMBER':1,'LINE_NUMBER_END':2} for k in ('a','b')]}
    GraphDiscovery(None,ws).relations(result,state,graph,{},calls,definition(ws)[0],lambda _:None,ws/'state.json')
    assert calls.n==2 and len(state['assembled']['mrg']['SOP'])==2
    assert state['relation_checks'][0]['status']=='failed'
    GraphDiscovery(None,ws).relations(result,state,graph,{},calls,definition(ws)[0],lambda _:None,ws/'state.json')
    assert calls.n==2
