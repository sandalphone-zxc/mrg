import copy
from kdiscovery.kd_s3_calls import ReservedCalls
from kdiscovery.kd_s3_support import relation_pairs
from kdiscovery.kd_s3_review import review_delta, normalize_verdicts
from test_v2_contracts import fixture, method


def test_inline_source_verdict_recovers_uncited_fact_without_extra_call(tmp_path):
    value,proof=fixture()
    class Model:
        folder=tmp_path
        requests=0
        def call(self,task,prompt,data):
            self.requests+=1
            return {'accepted':[{'id':c['id'],'path':'app.py','line':2} for c in data['claims']]}
    model=Model()
    result=review_delta(model,'x',value,proof,{},project_confirmed=True)
    assert result['decisions'][0]['keep'] and not result['drop_facts']
    assert {e['field'] for e in value['evidence']}=={'purpose','inputs/0'}
    fresh,_=fixture();review_delta(model,'x',fresh,proof,{},project_confirmed=True)
    assert model.requests==1 and len(fresh['evidence'])==2


def test_inline_bad_source_does_not_discard_valid_sibling():
    value,proof=fixture()
    batch=[{'id':k,'target_id':'SOP.x','field':f} for k,f in [('a','purpose'),('b','inputs/0')]]
    result={'accepted':[{'id':'a','path':'app.py','line':2},{'id':'b','path':'app.py','line':90}]}
    good,bad,fixed=normalize_verdicts(result,batch,value,proof)
    assert good==['a'] and bad[0]['id']=='b' and len(fixed)==1
    result['corrections']=[{'id':'a','path':'app.py','line':2}]
    assert normalize_verdicts(result,batch,value,proof)[0]==['a']
    result['corrections'][0]['line']=1
    assert not normalize_verdicts(result,batch,value,proof)[0]


def pair_state():
    values={}
    for key in ('a','b','c'):
        value,_=fixture();value['mrg']['SOP'][0].update(id=key,name='Business '+key)
        value['implementations']=[{'path':'app.py','symbol':key,'line':1}]
        values[key]={'value':value}
    return {'accepted':values,'relation_checks':[]}


def test_document_pairs_share_reservation_and_execution_candidate_list():
    state=pair_state()
    state['accepted']['a']['value']['pending_relations']=['Hand off to Business b']
    graph={'edges':[{'source':'a','target':'c','label':'AST'}]}
    assert relation_pairs(state,graph,[])==[('a','b')]
    state['relation_checks']=[{'ids':['b','a'],'status':'budget_pending'}]
    assert relation_pairs(state,graph,[])==[('a','b')]
    state['relation_checks'][0]['status']='reviewed'
    assert not relation_pairs(state,graph,[])


def test_shared_helper_without_cross_call_is_not_a_pair_but_multiple_owners_survive():
    state=pair_state();state['accepted']['b']['value']['implementations']=copy.deepcopy(state['accepted']['a']['value']['implementations'])
    definitions=[method('a'),method('c')]
    assert not relation_pairs(state,{'edges':[]},definitions)
    graph={'edges':[{'source':'a','target':'c','label':'METHOD_CALL'}]}
    assert relation_pairs(state,graph,definitions)==[('a','c'),('b','c')]


def test_review_leaves_actual_request_allowance_for_handoff_and_marks_gaps():
    value,proof=fixture()
    # More than one local review batch with genuinely distinct unresolved facts.
    value['mrg']['SOP'][0]['rules']=['Rule '+str(i) for i in range(27)]
    class Model:
        requests=21
        def remaining(self):return 24-self.requests
        def call(self,task,prompt,data):
            self.requests+=1
            return {'accepted':[{'id':c['id'],'path':'app.py','line':2} for c in data.get('claims',[])]}
    model=Model()
    result=review_delta(ReservedCalls(model,2),'x',value,proof,{},project_confirmed=True)
    assert model.requests==22 and model.remaining()==2
    assert value['mrg']['open_items'] and result['drop_facts']
    model.call('relations','',{});model.call('relations-repair','',{})
    assert model.requests==24


def test_zero_local_allowance_does_not_raise_and_abort_relation_stage():
    value,proof=fixture()
    class Model:
        def remaining(self):return 2
        def call(self,*args):raise AssertionError('Reserved allowance must survive')
    result=review_delta(ReservedCalls(Model(),2),'x',value,proof,{},project_confirmed=True)
    assert not result['decisions'][0]['keep'] and value['mrg']['open_items']
