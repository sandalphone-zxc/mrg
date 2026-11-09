"""Deterministic post-extraction work planning; clues never become proven edges."""
import copy,itertools,re
from .kd_s2_format import digest
from .kd_s2_evidence import merge_sources


def evidence_sources(materials, records, locators=(), limit=9000):
    """Use actual referenced lines, not string-searching 'path:line' at file start.

    Every selected source is from the frozen commit. Keep citation anchors first,
    then expand in round-robin order so one long definition cannot hide the other.
    """
    anchors={}
    for e in records:
        if isinstance(e.get('path'),str) and type(e.get('line')) is int:
            anchors.setdefault(e['path'],set()).add(e['line'])
    for hint in materials.normalize_hints(locators):
        path=hint.split(':')[0]
        if path not in anchors and any(x['path']==path for x in materials.tree):anchors[path]={1}
    sources={};queues=[];used=0;omitted=[]
    for path,points in anchors.items():
        f=materials.read(path)
        if not f:continue
        source={k:f[k] for k in ('sha256','kind','representation')};source['lines']=[];sources[path]=source
        spans=set()
        definitions=materials.architecture.get(path,{}).get('definitions',[])
        for line in sorted(points):
            if not 1<=line<=len(f['lines']):continue
            cost=len(f['lines'][line-1])+1
            if used+cost<=limit:source['lines'].append({'line':line,'text':f['lines'][line-1]});used+=cost
            else:omitted.append({'path':path,'next_line':line,'status':'not_read','reason':'补充任务证据锚点超出本包预算'})
            block=next((d for d in definitions if d['start']<=line<=d['end']),None)
            start,end=(block['start'],block['end']) if block else (max(1,line-15),min(len(f['lines']),line+35))
            spans.update(range(start,min(end,len(f['lines']))+1))
        queues.append((path,f,[i for i in sorted(spans) if i not in points]))
    for offset in range(max((len(q[2]) for q in queues),default=0)):
        for path,f,numbers in queues:
            if offset>=len(numbers):continue
            line=numbers[offset];cost=len(f['lines'][line-1])+1
            if used+cost>limit:
                if not any(o['path']==path for o in omitted):omitted.append({'path':path,'next_line':line,'status':'not_read','reason':'补充任务定义/章节尚未读完'})
                continue
            sources[path]['lines'].append({'line':line,'text':f['lines'][line-1]});used+=cost
    for value in sources.values():value['lines'].sort(key=lambda x:x['line'])
    materials.omissions.extend(omitted)
    return {p:s for p,s in sources.items() if s['lines']}


def detail_priority(entry):
    _,feature,_,_,value,_=entry;s=value['mrg']['SOP'][0]
    missing=int(not s['outputs'])+int(not s['completion_conditions'])+int(not value['mrg']['OMN'])
    return (-missing,feature.get('discovery_probe',False),s['id'])


def relation_groups(functions,pending,ledger,width=4):
    """Prioritize explicit cross-feature clues and compatible ports; then scan chunks.

    This is a bounded agenda, not an all-pairs independence proof.
    """
    ids={s['id'] for s in functions};aliases={}
    for s in functions:
        for key in (s['id'],s['name'],ledger.get(s['id'],{}).get('key')):
            if key:aliases.setdefault(key,set()).add(s['id'])
    groups=[]
    def add(values):
        key=tuple(sorted(set(values)&ids))
        if len(key)>1 and key not in groups:groups.append(key)
    for item in pending:
        text=str(item);matched=set()
        for key,values in aliases.items():
            if key in text:matched.update(values)
        ordered=sorted(matched)
        for i in range(0,len(ordered),width):add(ordered[i:i+width])
    for a,b in itertools.permutations(functions,2):
        if a.get('parent_sop_id')!=b.get('parent_sop_id'):continue
        for out in a['outputs']:
            for port in b['inputs']:
                if out['key'] not in ('data','result','id','response') and out['key']==port['key']:
                    add([a['id'],b['id']])
    # No pending hint does not mean that no workflow exists.
    by_parent={}
    for s in functions:by_parent.setdefault(s.get('parent_sop_id'),[]).append(s['id'])
    for values in by_parent.values():
        for i in range(0,len(values),width-1):add(values[i:i+width])
    return [list(g) for g in groups]


def relation_sources(materials,functions,evidence,pending,project_sources):
    result={}
    # Equal per-endpoint allocation includes both output and input/precondition evidence.
    for s in functions:
        records=[e for e in evidence if e['target_id']==s['id']]
        result=merge_sources(result,evidence_sources(materials,records,limit=3500))
    hints=[h for r in pending for h in r.get('locators',[]) if isinstance(h,str)]
    if hints:result=merge_sources(result,materials.windows(materials.select(hints)[:3],hints,limit=3000))
    # Overview evidence often contains the documented workflow omitted from individual SOP proofs.
    used=0;docs={}
    for path,source in project_sources.items():
        if source.get('kind') not in ('document','example'):continue
        selected=[]
        for line in source['lines']:
            cost=len(line['text'])+1
            if used+cost>3000:break
            selected.append(line);used+=cost
        if selected:docs[path]={**source,'lines':selected}
    return merge_sources(result,docs)


def namespace_relations(value,key):
    value=copy.deepcopy(value);mapping={}
    for edge in value.get('ME',[]):mapping[edge['id']]='ME.post.'+digest([key,edge['id']])[:18]
    proof_map={e['id']:'proof.post.'+digest([key,e['id']])[:18] for e in value.get('evidence',[])}
    for edge in value.get('ME',[]):
        edge['id']=mapping[edge['id']];edge['source_refs']=[proof_map.get(x,x) for x in edge['source_refs']]
    for e in value.get('evidence',[]):
        e['id']=proof_map[e['id']];e['target_id']=mapping.get(e['target_id'],e['target_id'])
    return value


def bind_relation_evidence(value):
    """An edge's explicit source_refs can disambiguate an endpoint pointer.

    The quote/line/meaning are unchanged. Shared evidence is cloned per edge;
    unsupported targets remain invalid instead of being silently reassigned.
    """
    value=copy.deepcopy(value);records={e['id']:e for e in value.get('evidence',[])}
    extras=[]
    for edge in value.get('ME',[]):
        refs=[]
        for ref in edge.get('source_refs',[]):
            e=records.get(ref)
            if e and e.get('field')=='meaning' and e.get('target_id') in (edge.get('source'),edge.get('target')):
                e=copy.deepcopy(e);e['original_target_id']=e['target_id'];e['target_id']=edge['id']
                e['id']='proof.bound.'+digest([edge['id'],ref])[:20];extras.append(e);ref=e['id']
            refs.append(ref)
        edge['source_refs']=refs
    value.setdefault('evidence',[]).extend(extras)
    return value
