"""KD-S-3 pointer normalization, without changing business facts or KD-S-2."""
import copy,re
from .kd_s2_format import digest

def line_anchors(value):
    """Normalize integer/string/range pointers, never evaluate model text."""
    if type(value) is int:return [value] if value>0 else []
    if not isinstance(value,str):return []
    text=value.strip().replace('–','-').replace('—','-')
    if not re.fullmatch(r'\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*',text):return []
    result=[]
    for part in text.split(','):
        points=[int(n.strip()) for n in part.split('-')]
        if any(n<1 for n in points) or (len(points)==2 and points[1]<points[0]):return []
        result.extend(points)
    return list(dict.fromkeys(result))

def normalize_evidence(value,proof,key='evidence'):
    result=copy.deepcopy(value);normalized=[];diagnostics=[]
    for ref in result.get(key,[]):
        source=proof.get(ref.get('path'),{});visible={l['line']:l['text'] for l in source.get('lines',[])}
        lines=[n for n in line_anchors(ref.get('line')) if visible.get(n,'').strip()]
        if not lines:
            diagnostics.append({'reference':ref,'reason':'定位格式无效或未指向本批可见原文；事实仍须复核，不自动删除。'});continue
        for n in lines:
            normalized.append({**{k:v for k,v in ref.items() if k!='quote'},'line':n})
    result[key]=normalized
    result.setdefault('locator_diagnostics',[]).extend(diagnostics)
    return result

def locator_matches(h,m):
    if isinstance(h,dict):
        path=h.get('path');symbol=h.get('symbol');line=h.get('line');anchors=line_anchors(line)
        return bool(path or symbol) and (not path or m['path']==path or m['path'].startswith(path.rstrip('/')+'/')) and (not symbol or symbol in (m['id'],m['symbol'],m['name']) or symbol.rsplit('::',1)[-1]==m['name']) and (not line or any(m['start']<=n<=m['end'] for n in anchors))
    if not isinstance(h,str):return False
    if h in (m['id'],m['path'],m['symbol'],m['name']):return True
    if h.startswith(m['path']+':'):
        tail=h[len(m['path']):].lstrip(':')
        return tail==m['name'] or tail==m['symbol'] or (tail.isdigit() and m['start']<=int(tail)<=m['end'])
    return m['path'].startswith(h.rstrip('/')+'/')

def normalize_raw(raw):
    value=copy.deepcopy(raw)
    for edge in value.get('links',[]):
        # Null on an unconditional edge means no condition, not a new assertion.
        if edge.get('condition') is None and edge.get('relation')!='conditional_next':edge['condition']=''
    return value

def locate_implementations(value,proof,definitions):
    for item in value.get('implementations',[]):
        matches=[n for n in definitions if n['path']==item.get('path') and locator_matches({'symbol':item.get('symbol')},n) and n['start']<=item.get('line',0)<=n['end']]
        if len(matches)!=1:continue
        n=matches[0];visible={l['line']:l['text'] for l in proof.get(n['path'],{}).get('lines',[])}
        if n['name'] not in visible.get(n['start'],''):continue
        item.update(original_symbol=item['symbol'],symbol=n['name'],line=n['start'])

def confirmed_roots(value,definitions):
    return {n['id'] for n in definitions for e in value.get('implementations',[])
            if locator_matches({'path':e.get('path'),'symbol':e.get('symbol'),'line':e.get('line')},n)}

def relation_pairs(state,graph,definitions):
    """One candidate source for scheduling and execution; never manufactures ME."""
    from collections import defaultdict
    owners=defaultdict(set);pairs=set();accepted=state.get('accepted',{})
    sops=[s for entry in accepted.values() for s in entry['value'].get('mrg',{}).get('SOP',[])]
    definitions=list(definitions)
    for sid,entry in accepted.items():
        for root in confirmed_roots(entry['value'],definitions):owners[root].add(sid)
    for edge in graph.get('edges',[]):
        if edge.get('label') not in ('METHOD_CALL','REACHING_DEF'):continue
        for a in owners.get(edge['source'],()):
            for b in owners.get(edge['target'],()):
                if a!=b:pairs.add(tuple(sorted((a,b))))
    for sid,entry in accepted.items():
        for clue in entry['value'].get('pending_relations',[]):
            for sop in sops:
                if sop['id']!=sid and (sop['id'] in str(clue) or sop['name'] in str(clue)):
                    pairs.add(tuple(sorted((sid,sop['id']))))
    done={tuple(sorted(row['ids'])) for row in state.get('relation_checks',[]) if row['status'] in ('reviewed','failed')}
    return sorted(pairs-done)

def corrected_evidence(value,corrections,lookup,proof):
    """Review may correct an anchor only to an actual visible source line."""
    entities={n['id']:n for k in ('SOP','OMN','MN','ME') for n in value['mrg'][k]}
    entities[value['mrg']['MNS']['id']]=value['mrg']['MNS']
    for correction in corrections:
        claim=lookup[correction['id']];path=correction.get('path');anchors=line_anchors(correction.get('line'))
        if not anchors:raise ValueError('复核来源行必须为有效行号')
        source=proof.get(path,{})
        line=next((n for n in anchors if any(l['line']==n and l['text'].strip() for l in source.get('lines',[]))),None)
        text=next((l['text'] for l in source.get('lines',[]) if l['line']==line),None)
        if not text or not text.strip():raise ValueError('复核定位必须位于可见原文')
        target=claim['target_id'];field=claim['field']
        e={'id':'proof.'+digest([target,field,path,line,text])[:20],'target_id':target,'field':field,'path':path,'line':line,'quote':text}
        value['evidence']=[old for old in value['evidence'] if not(old['target_id']==target and old['field']==field)]+[e]
        entities[target]['source_refs']=[old['id'] for old in value['evidence'] if old['target_id']==target]
