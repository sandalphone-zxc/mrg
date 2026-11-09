import copy,json
from pathlib import Path
import pytest
from fixtures import ws,FakeAPI,COMMIT
from test_kd_s3 import Model,fake_graph
from kdiscovery.kd_s3 import GraphDiscovery,incremental,merge_reviewed
from kdiscovery.kd_s3_index import parse_file,import_bindings
from kdiscovery.kd_s3_review import review_delta,claims

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('path,text,name',[
    ('x.py','class C:\n    def save(self):\n        return 1','save'),
    ('x.php','<?php function save($x) { return $x; }','save'),
    ('x.java','class C { public int save(int x) { return x; }}','save'),
    ('x.cpp','int save(int x) { return x; }','save'),
    ('x.scala','object C { def save(x: Int): Int = { x } }','save'),
    ('x.sh','save() { echo hi; }','save'),
    ('x.ts','export const save = (x: number) => x;','save'),
    ('x.vue','<template><div/></template>\n<script setup lang="ts">\nconst save = () => 1;\n</script>','save'),
])
def test_language_definitions_and_locations(path,text,name):
    definitions,_,_,_=parse_file(ROOT,path,text)
    found=next(n for n in definitions if n['NAME']==name)
    assert found['implementation_kind']=='concrete'
    assert name in text.splitlines()[found['LINE_NUMBER']-1]

def test_abstract_placeholder_is_not_concrete_and_final_pass_does_not_hide_work():
    d,_,_,_=parse_file(ROOT,'app.py','class A:\n    def a(self):\n        pass\n    def b(self):\n        save()\n        pass\n')
    assert {n['NAME']:n['implementation_kind'] for n in d}=={'a':'abstract','b':'concrete'}

def test_only_explicit_imports_resolve():
    assert import_bindings('pkg/a.py','from .b import save as persist',{'pkg/a.py','pkg/b.py'})=={'persist':('pkg/b.py','save')}
    assert import_bindings('a.ts',"import {save as persist} from './b'",{'a.ts','b.ts'})=={'persist':('b.ts','save')}
    assert import_bindings('a.ts',"import {save} from 'external'",{'a.ts','b.ts'})=={}

def test_cached_index_restores_material_inventory_and_explicit_calls(ws,monkeypatch):
    from kdiscovery.kd_s3_index import IndexMaterials,build
    monkeypatch.setattr('kdiscovery.kd_s3_index.hydrate_archive',lambda *a:None)
    api=FakeAPI({'README':b'Deliver','app.py':b'from worker import save\ndef deliver():\n    save()\n','worker.py':b'def save():\n    return 1\n'})
    first=IndexMaterials(ws,ws/'indexed','demo/example',COMMIT,api)
    graph,meta=build(first,ROOT)
    assert any(e['resolution']=='explicit_import_symbol_candidate' for e in graph['edges'])
    restored=IndexMaterials(ws,ws/'indexed','demo/example',COMMIT,api)
    again,_=build(restored,ROOT)
    assert restored.tree and restored.read('README') and again==graph

def test_native_crash_keeps_completed_files_and_skips_only_active_file(ws,monkeypatch):
    from kdiscovery.kd_s3_index import isolated_parse
    from kdiscovery.kd_s2_sources import atomic
    from types import SimpleNamespace
    rows=[{'path':p,'sha256':p,'source':p} for p in ('good.py','crash.py','next.py')];seen=[]
    def run(args,**kwargs):
        data=json.loads(Path(args[-1]).read_text(encoding='utf8'));batch=data['rows']
        for r in batch:
            seen.append(r['path']);atomic(Path(data['progress']),{'path':r['path']})
            if r['path']=='crash.py':return SimpleNamespace(returncode=139)
            atomic(Path(r['target']),{'path':r['path'],'definitions':[], 'calls':[], 'imports':[], 'limits':[]})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('kdiscovery.kd_s3_index.subprocess.run',run)
    result=isolated_parse(ROOT,ws,rows,{'fixed':'identity'})
    assert seen==['good.py','crash.py','next.py'] and len(result)==3
    assert next(r for r in result if r['path']=='crash.py')['limits']
    isolated_parse(ROOT,ws,rows,{'fixed':'identity'})
    assert seen==['good.py','crash.py','next.py']

def test_large_repository_skips_bulk_archive_not_source_material(ws,monkeypatch):
    from kdiscovery.kd_s3_index import hydrate_archive
    from kdiscovery.kd_s2_sources import atomic
    from types import SimpleNamespace
    atomic(ws/'inventory.json',{'tree':[{'path':'video.bin','size':40_000_000},{'path':'app.py','size':100}]})
    m=SimpleNamespace(folder=ws,tree=[{'path':'app.py','kind':'implementation'}],repo='demo/repo',commit=COMMIT)
    def unexpected(*a):raise AssertionError('Must not download large archive')
    monkeypatch.setattr('kdiscovery.kd_s3_index.fetch_archive',unexpected)
    notes=[];hydrate_archive(m,notes.append)
    assert notes and m.tree[0]['path']=='app.py'

def test_novel_review_does_not_resend_confirmed_facts_and_rejects_missing_verdict(ws,monkeypatch):
    monkeypatch.setattr('kdiscovery.kd_s3.build',fake_graph)
    api=FakeAPI({'README':b'Deliver documents.','app.py':b'def deliver(document):\n    save(document)\n    return document\n'})
    result=GraphDiscovery(Model(),ws,api).extract({'repo':'demo/example','commit':COMMIT},{},{},'novel')
    state=json.loads((Path(result['folder'])/'work-state.json').read_text(encoding='utf8'))
    base=next(iter(state['accepted'].values()));value=copy.deepcopy(base['value'])
    class Calls:
        def call(self,*a):raise AssertionError('No new facts means no new model request')
    review=review_delta(Calls(),'same',value,base['proof'],{},value,True)
    assert review['reviewed_new_facts']==0
    class Incomplete:
        def call(self,*a):return {'accepted':[],'rejected':[],'unknown':[]}
    review=review_delta(Incomplete(),'new',value,base['proof'],{})
    assert not review['project_supported']
    assert all(not d['keep'] for d in review['decisions'])
    assert review['drop_facts']  # Missing verdicts are withheld, not silently accepted.

def test_scope_expansion_requires_source_without_destroying_prior_contract():
    base={'mrg':{'SOP':[{'id':'SOP.x','name':'Read','purpose':'Read item','inputs':[], 'outputs':[], 'rules':[], 'preconditions':[], 'completion_conditions':[], 'exceptions':[]}]},'evidence':[],'implementations':[]}
    pending=incremental({'scope_extension':{'name':'Manage','purpose':'Manage item'}},base)
    assert pending['sop']['purpose']=='Read item' and pending['gaps']
    raw={'scope_extension':{'name':'Manage','purpose':'Read and create items','previous_goal':'Read item','reason':'Create joins the existing read goal'},'evidence':[{'target':'sop','field':'purpose','path':'x.py','line':4}]}
    value=incremental(raw,base)
    assert value['sop']['purpose']=='Read and create items'
    assert base['mrg']['SOP'][0]['purpose']=='Read item'
