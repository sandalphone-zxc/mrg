import copy,json
from pathlib import Path
from fixtures import ws,FakeAPI,COMMIT
from test_kd_s3 import Model,fake_graph
from kdiscovery.kd_s3 import schedule,GraphDiscovery
from kdiscovery.kd_s3_packages import behavior_packages,repair_package,pair_sources


def node(i,path,name,start=1,end=3):
    return {'id':i,'label':'METHOD','path':path,'NAME':name,'FULL_NAME':path+'.'+name,'LINE_NUMBER':start,'LINE_NUMBER_END':end}


def test_business_candidates_precede_infrastructure_across_modules():
    graph={'methods':[node('a','eslint.config.js','config'),node('b','src/views/orders.vue','handleSubmit'),node('c','app/export.py','export_records')]}
    features,byid=schedule({'features':[{'key':'export','name':'Export','goal':'Export','locators':['app/export.py']}]},graph,'demo/repo')
    assert features[0]['document_candidate'] and features[1]['roots']==['b'] and features[-1]['roots']==['a']


def test_sibling_entries_keep_separate_paths_without_inventing_relations():
    graph={'methods':[node('a','app.py','create_order'),node('b','app.py','cancel_order')],'edges':[]}
    features,byid=schedule({'features':[]},graph,'demo/repo')
    def read(ms):return {m['path']:{'sha256':'x','lines':[{'line':1,'text':m['name']}]} for m in ms}
    packages=behavior_packages(features[0],graph,byid,read)
    assert packages and all(len(p['graph']['nodes'])==1 and p['graph']['edges']==[] for p in packages)
    assert len(features)==1  # reading package does not become a separate SOP


def test_repair_shrinks_even_when_already_below_previous_threshold():
    package={'sources':{'app.py':{'sha256':'x','lines':[{'line':i,'text':'a'} for i in range(1,5)]}},'entry':{},'graph':{}}
    parts=repair_package(package)
    assert len(parts)>1 and parts[0]['sources']!=package['sources']
    assert [l['line'] for p in parts for s in p['sources'].values() for l in s['lines']]==[1,2,3,4]


def test_technical_first_page_does_not_abandon_candidate(ws,monkeypatch):
    def graph(materials,*a):
        g,m=fake_graph(materials,*a)
        g['methods']=[node('a','app.py','a_helper',1,1),node('b','app.py','z_delivery',2,3)];g['nodes']=g['methods']
        return g,m
    monkeypatch.setattr('kdiscovery.kd_s3.build',graph)
    from kdiscovery.kd_s3_packages import behavior_packages as pack
    def pages(f,g,b,reader):
        return [p for r in f['roots'] for p in pack({**f,'roots':[r]},g,b,reader)]
    monkeypatch.setattr('kdiscovery.kd_s3.behavior_packages',pages)
    class Probe(Model):
        def json_background(self,p,d):
            if d.get('behavior_entry',{}).get('id')=='a':
                self.calls.append(copy.deepcopy(d));return {'sop':None,'gaps':['helper only']}
            return super().json_background(p,d)
    model=Probe();api=FakeAPI({'README':b'Deliver documents.','app.py':b'helper = True\n    save(document)\n    return document\n'})
    result=GraphDiscovery(model,ws,api).extract({'repo':'demo/example','commit':COMMIT},{},{},'next-page')
    m=json.loads((Path(result['folder'])/'mrg.json').read_text(encoding="utf8"));assert len(m['SOP'])==1
    state=json.loads((Path(result['folder'])/'work-state.json').read_text(encoding="utf8"));entry=next(iter(state['ledger'].values()))
    assert entry['pages_read']==2 and len(entry['skipped_pages'])==1


def test_relation_work_package_keeps_both_sides_under_source_limit():
    state={'ledger':{},'accepted':{}}
    for sid in ('a','b'):
        state['ledger'][sid]={'roots':[]}
        state['accepted'][sid]={'proof':{sid+'.py':{'sha256':sid,'lines':[{'line':i,'text':'value = '+('x'*200)} for i in range(1,300)]}},
            'value':{'evidence':[{'target_id':sid,'path':sid+'.py','line':100}], 'implementations':[]}}
    proof=pair_sources(('a','b'),state,{'edges':[]},{})
    assert set(proof)=={'a.py','b.py'}
    assert sum(len(l['text'])+1 for s in proof.values() for l in s['lines'])<=8000
    assert all(any(l['line']==100 for l in s['lines']) for s in proof.values())


def test_truncated_small_request_repairs_with_different_scope(ws,monkeypatch):
    monkeypatch.setattr('kdiscovery.kd_s3.build',fake_graph)
    class Truncate(Model):
        failed=False
        def json_background(self,p,d):
            if 'behavior_entry' in d and not self.failed:
                self.failed=True;self.calls.append(copy.deepcopy(d));raise ValueError('truncated output')
            return super().json_background(p,d)
    model=Truncate();api=FakeAPI({'README':b'Deliver documents.','app.py':b'def deliver(document):\n    save(document)\n    return document\n'})
    GraphDiscovery(model,ws,api).extract({'repo':'demo/example','commit':COMMIT},{},{},'repair')
    requests=[d for d in model.calls if 'behavior_entry' in d]
    assert len(requests)>=2 and requests[0]!=requests[1]
    assert requests[1]['repair_scope']=='minimal_behavior_only'
    assert requests[0]['sources']!=requests[1]['sources']


def test_followup_uses_delta_without_rewriting_confirmed_contract(ws,monkeypatch):
    def graph(materials,*a):
        g,m=fake_graph(materials,*a);g['methods']=[node('a','app.py','a_save',1,2),node('b','app.py','b_deliver',3,3)];g['nodes']=g['methods'];return g,m
    monkeypatch.setattr('kdiscovery.kd_s3.build',graph)
    from kdiscovery.kd_s3_packages import behavior_packages as pack
    def pages(f,g,b,reader):
        return [p for r in f['roots'] for p in pack({**f,'roots':[r]},g,b,reader)]
    monkeypatch.setattr('kdiscovery.kd_s3.behavior_packages',pages)
    class Increment(Model):
        def json_background(self,p,d):
            if 'confirmed_contract' in d:
                self.calls.append(copy.deepcopy(d))
                return {'steps':[{'key':'deliver','name':'Deliver document','purpose':'Deliver document','actor':'system'}],
                    'evidence':[{'target':'deliver','field':'purpose','path':'app.py','line':3}]}
            return super().json_background(p,d)
    model=Increment();api=FakeAPI({'README':b'Deliver documents.','app.py':b'def deliver(document):\n    save(document)\n    return document\n'})
    a=GraphDiscovery(model,ws,api).extract({'repo':'demo/example','commit':COMMIT},{},{},'increments')
    m=json.loads((Path(a['folder'])/'mrg.json').read_text(encoding='utf8'))
    assert len(m['SOP'])==1 and len(m['OMN'])==2
    assert any('confirmed_contract' in d and 'previous_capability' not in d for d in model.calls)
