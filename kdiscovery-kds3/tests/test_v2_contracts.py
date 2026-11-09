import copy
from pathlib import Path
import pytest
from kdiscovery.kd_s3_support import locator_matches,corrected_evidence,normalize_raw,locate_implementations
from kdiscovery.kd_s3_index import generated_reason
from kdiscovery.kd_s3_review import review_delta,apply_review
from kdiscovery.kd_s3_packages import behavior_packages

def method(name,start=1,end=3):
    return dict(id=name,name=name,symbol='app.py::'+name,path='app.py',start=start,end=end,module='app',implementation_kind='concrete')

def fixture():
    s=dict(id='SOP.x',name='Save',purpose='Save an item',inputs=[dict(key='item',name='Item',meaning='Item to save',necessity='required')],outputs=[],rules=[],preconditions=[],completion_conditions=[],exceptions=[],input_bindings=[],output_bindings=[],source_refs=[])
    value={'mrg':{'MNS':dict(id='MNS.x',goal=''), 'SOP':[s],'OMN':[],'MN':[],'ME':[],'open_items':[]},'evidence':[],'implementations':[]}
    proof={'app.py':dict(sha256='a',kind='implementation',representation='original',lines=[dict(line=1,text='def save(item):'),dict(line=2,text='    return store(item)')])}
    return value,proof

def test_exact_qualified_locator_does_not_select_entire_file():
    a,b=method('save'),method('load')
    assert locator_matches('app.py::save',a) and not locator_matches('app.py::save',b)
    assert locator_matches({'path':'app.py','symbol':'save'},a) and not locator_matches({'path':'app.py','symbol':'save'},b)

def test_review_repairs_uncited_contract_against_visible_source(tmp_path):
    value,proof=fixture()
    class Model:
        folder=tmp_path
        def call(self,task,prompt,data):
            return dict(accepted=[c['id'] for c in data['claims']],rejected=[],unknown=[],corrections=[dict(id=c['id'],path='app.py',line=1) for c in data['claims']])
    r=review_delta(Model(),'x',value,proof,{},project_confirmed=True)
    assert not r['drop_facts'] and len(value['evidence'])==2
    assert {e['field'] for e in value['evidence']}=={'purpose','inputs/0'}
    class Resume(Model):
        def call(self,*args):raise AssertionError('Successful verdicts must not repeat')
    again,_=fixture();review_delta(Resume(),'repair',again,proof,{},project_confirmed=True,repair=True)
    assert len(again['evidence'])==2

def test_uncited_positive_is_not_accepted_as_evidence():
    value,proof=fixture()
    class Model:
        def call(self,task,prompt,data):return dict(accepted=[c['id'] for c in data['claims']],rejected=[],unknown=[])
    r=review_delta(Model(),'x',value,proof,{},project_confirmed=True)
    assert not r['decisions'][0]['keep'] and r['drop_facts']

def test_invisible_correction_rejected():
    value,proof=fixture()
    with pytest.raises(ValueError,match='可见'):
        corrected_evidence(value,[dict(id='f',path='app.py',line=30)],{'f':dict(target_id='SOP.x',field='purpose')},proof)

def test_qualified_implementation_maps_to_actual_definition():
    value,proof=fixture();value['implementations']=[dict(target_id='SOP.x',path='app.py',line=2,symbol='app.py::save')]
    locate_implementations(value,proof,[method('save')])
    assert value['implementations'][0]['symbol']=='save' and value['implementations'][0]['line']==1

def test_nullable_condition_does_not_invent_conditional_branch():
    raw={'links':[dict(relation='delivery',condition=None),dict(relation='conditional_next',condition=None)]}
    normalized=normalize_raw(raw)
    assert normalized['links'][0]['condition']=='' and normalized['links'][1]['condition'] is None
    assert raw['links'][0]['condition'] is None

def test_distribution_detection_is_content_based_not_project_name():
    assert generated_reason('normal.js','define.amd;factory(exports);'+'a'*100001)
    assert generated_reason('app.py','# generated file\n...')
    assert not generated_reason('components/widget.js','export function run() { return 1; }')

def test_entry_before_helper_and_long_document_continuation_preserved():
    a=method('run',50,54);a['behavior_start']=53
    b=method('_helper',1,4);byid={'run':a,'_helper':b}
    graph={'edges':[dict(source='run',target='_helper',label='METHOD_CALL')]}
    def read(ms):
        n=ms[0];lines=[dict(line=i,text=('d'*9000 if i==51 else 'code '+str(i))) for i in range(n['start'],n['end']+1)]
        return {'app.py':dict(sha256='a',kind='implementation',representation='original',lines=lines)}
    pages=behavior_packages(dict(roots=['run']),graph,byid,read)
    first=[l['line'] for l in pages[0]['sources']['app.py']['lines']]
    assert first==[50,53,54]
    all_lines={l['line'] for p in pages for s in p['sources'].values() for l in s['lines']}
    assert all_lines==set(range(50,55))|set(range(1,5))
