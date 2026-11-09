import copy,json
from pathlib import Path
from kdiscovery.kd_s3_branches import prepare_branch,carry_existing_nodes
from kdiscovery.kd_s3 import GraphDiscovery
from kdiscovery.kd_s2_report import verify
from fixtures import ws,FakeAPI,COMMIT,port
from test_kd_s3 import Model,fake_graph


def raw_branch(key='create',name='创建',condition='尚未创建'):
    return {'sop':{'name':'内容管理','purpose':'管理内容的发布生命周期'},
        'branch':{'key':key,'name':name,'trigger':'提交'+name+'请求','inputs':[port('content')],
                  'outputs':[port('result')],'preconditions':[condition],'completion_conditions':[name+'完成']},
        'steps':[{'key':'operate','name':'处理内容','purpose':name+'内容','actor':'system','inputs':['content'],'outputs':['result']}],
        'evidence':[{'target':'sop','field':'purpose','path':'README','line':1}]+
            [{'target':'branch','field':f,'path':'app.py','line':2} for f in ('trigger','inputs/0','outputs/0','preconditions/0','completion_conditions/0')]+
            [{'target':'operate','field':'purpose','path':'app.py','line':2}],
        'input_bindings':[{'input_key':'content','step':'operate','node_input_key':'content','meaning':'本分支消费内容'}],
        'output_bindings':[{'output_key':'result','step':'operate','node_output_key':'result','meaning':'本分支结果'}]}


def test_branch_requirements_never_become_universal():
    value=prepare_branch(raw_branch())
    s=value['sop'];assert s['name']=='内容管理'
    assert s['inputs'][0]['necessity']=='optional'
    assert 'required' in s['inputs'][0]['meaning'] and '创建分支' in s['inputs'][0]['meaning']
    assert s['preconditions']==['【创建分支】尚未创建']
    assert value['steps'][0]['inputs'][0]['necessity']=='required'
    assert value['input_bindings'][0]['input_key']==s['inputs'][0]['key']


def test_same_local_port_and_step_names_do_not_collide_between_branches():
    a=prepare_branch(raw_branch());b=prepare_branch(raw_branch('remove','撤回','已发布'))
    assert a['sop']['inputs'][0]['key']!=b['sop']['inputs'][0]['key']
    assert a['steps'][0]['key']!=b['steps'][0]['key']
    assert a['steps'][0]['inputs'][0]['key']==b['steps'][0]['inputs'][0]['key']=='content'


def test_reference_expansion_preserves_field_provenance():
    value=prepare_branch(raw_branch());key=value['steps'][0]['key']
    proof=[e for e in value['evidence'] if e['target']==key and e['field']=='inputs/0']
    assert proof and proof[0]['path']=='app.py' and proof[0]['line']==2
    assert not any(e.get('target')=='branch' for e in value['evidence'])


def test_nested_evidence_matches_top_level_and_scopes_branch_doubt():
    raw=raw_branch();expected=prepare_branch(raw)
    nested=copy.deepcopy(raw);nested.pop('evidence')
    for e in raw['evidence']:
        owner=nested['sop'] if e['target']=='sop' else nested['branch'] if e['target']=='branch' else nested['steps'][0]
        owner.setdefault('evidence',[]).append(e)
    nested['uncertainties']=[{'target':'branch','field':'trigger','reason':'只涉及当前触发条件'}]
    actual=prepare_branch(nested)
    signature=lambda xs:{json.dumps(x,sort_keys=True) for x in xs}
    assert signature(actual['evidence'])==signature(expected['evidence'])
    assert actual['uncertainties'][0]['target']=='sop'
    assert actual['uncertainties'][0]['field'].startswith('rules/')
    assert actual['uncertainties'][0]['field']!='purpose'


def test_unpublished_branch_doubt_stays_gap_not_whole_sop_rejection():
    raw=raw_branch();raw['uncertainties']=[{'target':'branch','field':'unread','reason':'未读分支'}]
    actual=prepare_branch(raw)
    assert not actual['uncertainties'] and any('局部疑点' in s for s in actual['gaps'])


def test_review_can_resolve_binding_nodes_without_entire_graph():
    from kdiscovery.kd_s3_review import related_nodes
    value={'mrg':{'SOP':[{'id':'s','name':'Delivery','purpose':'Deliver result'}],
        'OMN':[{'id':'a','name':'Save result','purpose':'Store result','outputs':[{'key':'saved','meaning':'Persisted result'}]},
               {'id':'unrelated','name':'Other','purpose':'Unrelated flow'}],'MN':[]}}
    batch=[{'target_id':'s','value':{'node_id':'a','node_output_key':'saved','output_key':'delivery'}}]
    ctx=related_nodes(value,batch)
    assert {n['id'] for n in ctx}=={'s','a'}
    assert next(n for n in ctx if n['id']=='a')['outputs'][0]['meaning']=='Persisted result'


def test_removed_binding_evidence_is_not_reassigned_to_next_binding():
    from kdiscovery.kd_s3_review import binding_snapshot,sync_binding_evidence
    sop={'id':'s','input_bindings':[{'input_key':'a'},{'input_key':'b'}],'output_bindings':[],'source_refs':['ea','eb']}
    value={'mrg':{'SOP':[sop]},'evidence':[{'id':'ea','target_id':'s','field':'input_bindings/0'},{'id':'eb','target_id':'s','field':'input_bindings/1'}]}
    old=binding_snapshot(value);sop['input_bindings'].pop(0);sync_binding_evidence(value,old)
    assert value['evidence']==[{'id':'eb','target_id':'s','field':'input_bindings/0'}]
    assert sop['source_refs']==['eb']


def test_binding_sync_preserves_unrelated_field_evidence():
    from kdiscovery.kd_s3_review import binding_snapshot,sync_binding_evidence
    sop={'id':'s','input_bindings':[{'input_key':'a'}],'output_bindings':[],'source_refs':['ea','ep']}
    value={'mrg':{'SOP':[sop]},'evidence':[{'id':'ea','target_id':'s','field':'input_bindings/0'},{'id':'ep','target_id':'s','field':'purpose'}]}
    old=binding_snapshot(value);sop['input_bindings']=[];sync_binding_evidence(value,old)
    assert value['evidence']==[{'id':'ep','target_id':'s','field':'purpose'}]


def test_unread_trigger_is_not_published_as_supported_rule():
    raw=raw_branch();raw['evidence']=[e for e in raw['evidence'] if e['field']!='trigger']
    value=prepare_branch(raw)
    assert not any('触发' in rule for rule in value['sop']['rules'])
    assert not value['branch_record']['trigger_supported'] and value['gaps']


def test_prior_internal_nodes_available_for_explicit_cross_page_links():
    base={'mrg':{'OMN':[{'id':'old'}],'MN':[],'ME':[]},'evidence':[{'id':'e','target_id':'old'}]}
    draft={'mrg':{'OMN':[{'id':'new'}],'MN':[],'ME':[{'id':'link','source':'old','target':'new'}]},'evidence':[]}
    carry_existing_nodes(draft,base)
    assert {n['id'] for n in draft['mrg']['OMN']}=={'old','new'} and draft['evidence'][0]['id']=='e'


def test_two_business_branches_remain_one_sop_and_roundtrip(ws,monkeypatch):
    monkeypatch.setattr('kdiscovery.kd_s3.build',fake_graph)
    def packages(feature,graph,byid,reader):
        proof=reader(list(byid.values()))
        return [{'sources':proof,'entry':{'branch':key},'continuation':0,'definition_pages':1,'graph':{'nodes':[],'edges':[]}} for key in ('create','remove')]
    monkeypatch.setattr('kdiscovery.kd_s3.behavior_packages',packages)
    class BranchModel(Model):
        def json_background(self,p,data):
            if 'project_id' in data:return super().json_background(p,data)
            if 'claims' in data:return super().json_background(p,data)
            self.calls.append(copy.deepcopy(data));key=data['behavior_entry']['branch']
            return raw_branch(key,'创建' if key=='create' else '撤回','尚未创建' if key=='create' else '已发布')
    model=BranchModel();api=FakeAPI({'README':b'Manage content lifecycle.','app.py':b'def deliver(content):\n    save(content)\n    return content\n'})
    result=GraphDiscovery(model,ws,api).extract({'repo':'demo/example','commit':COMMIT},{},{},'branches')
    folder=Path(result['folder']);verify(folder)
    m=json.loads((folder/'mrg.json').read_text(encoding='utf8'));c=json.loads((folder/'coverage.json').read_text(encoding='utf8'))
    assert len(m['SOP'])==1 and m['SOP'][0]['name']=='内容管理' and len(m['OMN'])==2
    assert len(c['branches'])==2 and not m['ME']
    assert m['SOP'][0]['preconditions']==['【创建分支】尚未创建','【撤回分支】已发布']
    assert all(p['necessity']=='optional' for p in m['SOP'][0]['inputs'])
    assert len({p['key'] for p in m['SOP'][0]['outputs']})==2
    assert '功能内的业务分支' in (folder/'report.html').read_text(encoding='utf8')
    count=len(model.calls);GraphDiscovery(model,ws,api).extract({'repo':'demo/example','commit':COMMIT},{},{},'branches')
    assert len(model.calls)==count
