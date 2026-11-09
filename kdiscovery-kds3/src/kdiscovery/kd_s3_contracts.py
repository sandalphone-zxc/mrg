"""Local protocol recovery and explicit boundary changes; no inferred business facts."""
import copy
import json
import re
from .kd_s2_format import digest
from .kd_s2_sources import atomic
from .kd_s3_calls import ServicePause
from .kd_s2 import BudgetPause


def overview_prefix(text):
    """Read complete top-level values and complete feature objects, never close broken JSON."""
    decoder=json.JSONDecoder();result={};pos=text.find('{')+1
    if not pos:return result
    while pos<len(text):
        match=re.match(r'\s*,?\s*',text[pos:]);pos+=match.end()
        try:key,end=decoder.raw_decode(text,pos)
        except ValueError:break
        if not isinstance(key,str):break
        match=re.match(r'\s*:\s*',text[end:])
        if not match:break
        pos=end+match.end()
        if key=='features' and text[pos:pos+1]=='[':
            values=[];pos+=1
            while pos<len(text):
                match=re.match(r'\s*,?\s*',text[pos:]);pos+=match.end()
                if text[pos:pos+1]==']':pos+=1;break
                try:value,pos=decoder.raw_decode(text,pos)
                except ValueError:break
                if isinstance(value,dict):values.append(value)
            result[key]=values
            if text[pos:pos+1]!=',':break
        else:
            try:value,pos=decoder.raw_decode(text,pos)
            except ValueError:break
            result[key]=value
    return result


def clean_overview(raw, units):
    raw=copy.deepcopy(raw) if isinstance(raw,dict) else {}
    raw.setdefault('project',{});raw.setdefault('project_evidence',[]);raw.setdefault('gaps',[])
    valid={u['id'] for u in units};features=[]
    # Legacy reverse mappings are normalized once so extraction sees the same boundary.
    reverse={}
    for row in raw.get('document_coverage',[]):
        if isinstance(row,dict):
            for key in row.get('feature_keys',[]):reverse.setdefault(key,[]).append(row.get('unit_id'))
    for f in raw.get('features',[]):
        if not isinstance(f,dict) or not all(isinstance(f.get(k),str) and f[k].strip() for k in ('name','goal')):
            raw['gaps'].append('概览候选结构不完整，保留为待辨认：'+str(f));continue
        f['key']=f.get('key') or digest([f['name'],f['goal']])[:16]
        f['document_units']=sorted(set(f.get('document_units',[])+reverse.get(f['key'],[]))&valid)
        if not isinstance(f.get('locators',[]),list):f['locators']=[f['locators']]
        features.append(f)
    raw['features']=features
    return raw


def obtain_overview(calls,prompt,data,state,path):
    if state.get('overview_result') is not None:return copy.deepcopy(state['overview_result'])
    partial=state.get('overview_partial',{})
    for attempt in range(2):
        task='overview' if attempt==0 else 'overview-repair'
        if task in state.get('overview_failed_tasks',[]):continue
        state.setdefault('overview_attempts',[]).append(task);atomic(path,state)
        payload=copy.deepcopy(data)
        if attempt:
            payload['architecture']=[]
            payload['already_preserved_features']=[{'key':f.get('key'),'name':f.get('name')} for f in partial.get('features',[])]
            payload['repair_scope']='紧凑补齐项目描述与未保留功能，不展开步骤，不逐段解释，不重复已保留功能。'
        try:
            got=calls.call(task,prompt,payload)
            combined={**partial,**got}
            combined['features']=partial.get('features',[])+got.get('features',[])
            unique={f.get('key') or digest(f):f for f in combined['features'] if isinstance(f,dict)}
            combined['features']=list(unique.values())
            result=clean_overview(combined,data['document_units'])
            state['overview_result']=result;atomic(path,state);return result
        except (ServicePause,BudgetPause):raise
        except (ValueError,TypeError,KeyError) as exc:
            recovered=overview_prefix(getattr(exc,'response_content',''))
            partial={**partial,**recovered,'features':partial.get('features',[])+recovered.get('features',[])}
            state['overview_partial']=partial
            state.setdefault('overview_failed_tasks',[]).append(task)
            state.setdefault('failures',[]).append({'phase':'overview','attempt':attempt,'reason':str(exc),'partial_features':len(partial.get('features',[]))})
            atomic(path,state)
        except Exception as exc:
            if getattr(exc,'diagnostic',{}).get('code') not in ('truncated','invalid_json','empty_content','output_budget'):raise
            recovered=overview_prefix(getattr(exc,'response_content',''))
            partial={**partial,**recovered,'features':partial.get('features',[])+recovered.get('features',[])}
            state['overview_partial']=partial
            state.setdefault('overview_failed_tasks',[]).append(task)
            state.setdefault('failures',[]).append({'phase':'overview','attempt':attempt,'reason':str(exc),'partial_features':len(partial.get('features',[]))})
            atomic(path,state)
    result=clean_overview(partial,data['document_units'])
    result['gaps'].append('概览未完整生成；完整候选已保留，未归属文档与入口继续作为线索。')
    state['overview_result']=result;atomic(path,state);return result


def normalize_delta(raw):
    """Discard only malformed optional fields, recording every removal. No semantic guessing."""
    value=copy.deepcopy(raw);gaps=value.setdefault('gaps',[])
    if not isinstance(gaps,list):value['gaps']=gaps=[str(gaps)]
    additions=value.get('contract_additions')
    if additions is not None and not isinstance(additions,dict):
        gaps.append('契约补充结构错误，未采用该字段：'+str(additions));value['contract_additions']={}
    for field,items in list(value.get('contract_additions',{}).items()):
        if field not in ('inputs','outputs','rules','preconditions','completion_conditions','exceptions') or not isinstance(items,list):
            gaps.append('契约补充字段格式错误，未采用：'+field);del value['contract_additions'][field];continue
        for i,item in enumerate(items):
            if field in ('inputs','outputs') and (not isinstance(item,dict) or not item.get('key')):
                # Preserve original indexes for subsequent evidence. Remove its citation so
                # refinement_delta skips this item before looking at the malformed port.
                gaps.append('补充端口格式错误，未采用：'+field+'/'+str(i))
                value['evidence']=[e for e in value.get('evidence',[]) if not(isinstance(e,dict) and e.get('target')=='sop' and e.get('field')==f'contract_additions/{field}/{i}')]
    for field in ('evidence','implementations','uncertainties'):
        items=value.get(field,[]) or []
        value[field]=[x for x in items if isinstance(x,dict)] if isinstance(items,list) else []
        if len(value[field])!=len(items):gaps.append('非对象定位记录未采用：'+field)
    excluded=set()
    for field in ('steps','states'):
        retained=[]
        for step in value.get(field,[]) or []:
            if not isinstance(step,dict):gaps.append('步骤结构错误：'+str(step));continue
            ownership=step.pop('ownership',None);reason=step.pop('ownership_reason','')
            if ownership=='other':
                excluded.add(step.get('key'));gaps.append('另属业务目标的步骤未合入：'+str(step)+'；'+reason);continue
            if ownership=='unknown':value['uncertainties'].append({'target':step.get('key'),'field':'purpose','reason':reason or '步骤与当前业务目标的归属不确定'})
            retained.append(step)
        value[field]=retained
    if excluded:
        value['links']=[e for e in value.get('links',[]) if e.get('source') not in excluded and e.get('target') not in excluded]
        for field in ('input_bindings','output_bindings'):value[field]=[e for e in value.get(field,[]) if e.get('step') not in excluded]
        for field in ('evidence','implementations'):value[field]=[e for e in value[field] if e.get('target') not in excluded]
    return value
