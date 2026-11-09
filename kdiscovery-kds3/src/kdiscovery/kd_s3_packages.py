"""Generic business-entry ordering and bounded, resumable source work packages.

These are reading priorities, never assertions that a method is a business SOP.
No repository names, domain-specific paths or baseline functionality are used.
"""
import collections,copy,re
from .kd_s2_format import digest
from .kd_s2_units import split_sources
from .kd_s2_evidence import merge_sources


def entry_rank(method):
    if method.get('implementation_kind')=='distribution':return 3
    path=method['path'].lower();name=method.get('name','')
    filename=path.rsplit('/',1)[-1]
    technical=(bool(re.search(r'(^|/)(tests?|__tests__|fixtures|mocks|vendor|node_modules)(/|$)',path)) or
               bool(re.search(r'(^|[._-])(config|spec|test)([._-]|$)',filename)) or
               bool(re.search(r'(^|/)(scripts|migrations|utils|utilities)(/|$)',path)))
    if technical:return 3
    action=bool(re.search(r'^(handle|on[A-Z_]|submit|create|update|delete|remove|save|send|fetch|get|list|search|run|execute|process|import|export|upload|download|analyze|calculate|cancel|confirm|pay|publish|deliver)',name))
    interface=bool(re.search(r'(^|/)(views|pages|routes|controllers|handlers|commands|cli|clis|api|jobs|tasks|services)(/|$)',path))
    if action and interface:return 0
    if action or interface:return 1
    return 2


def ordered_features(features,byid):
    """Business tier first, then module fairness; infrastructure never jumps ahead."""
    groups=collections.defaultdict(lambda:collections.defaultdict(list))
    for f in features:
        tier=0 if f.get('document_candidate') else 1+min((entry_rank(byid[r]) for r in f['roots'] if r in byid),default=3)
        f['reading_priority']=tier;groups[tier][f['module']].append(f)
    result=[]
    for tier in sorted(groups):
        modules=groups[tier]
        for values in modules.values():values.sort(key=lambda f:f['id'])
        while any(modules.values()):
            for module in sorted(modules):
                if modules[module]:result.append(modules[module].pop(0))
    return result


def behavior_packages(feature,graph,byid,read_methods):
    """One entry and its immediate implementation per resumable business-reading path.

    The graph stays a locator. Preserve omitted expansion frontiers explicitly;
    no global dataflow, recursive expansion, or file-to-SOP conversion.
    """
    adj=collections.defaultdict(set)
    for e in graph['edges']:
        if e['label']=='METHOD_CALL' and e['target'] in byid:adj[e['source']].add(e['target'])
    roots=sorted((r for r in set(feature['roots']) if r in byid),key=lambda r:(byid[r]['name'].startswith('_'),entry_rank(byid[r]),byid[r]['path'],byid[r]['start'],r))
    packages=[];seen_lines=set()
    for root in roots:
        direct=sorted(adj[root]-{root},key=lambda r:(entry_rank(byid[r]),byid[r]['path'],byid[r]['start']))
        selected=[root]+direct[:8]
        frontier=sorted(set(direct[8:])|{v for r in direct[:8] for v in adj[r] if v not in selected})
        parts=[];current={};used=0
        for r in selected:
            for path,source in read_methods([byid[r]]).items():
                first=byid[r].get('behavior_start') or byid[r]['start'];rows=source['lines']
                header=[l for l in rows if l['line']==byid[r]['start']]
                ordered=header+[l for l in rows if l['line']>=first and l not in header]+[l for l in rows if l['line']<first and l not in header]
                for row in ordered:
                    key=(path,row['line'])
                    if key in seen_lines:continue
                    cost=len(row['text'])+1
                    if current and used+cost>9000:parts.append(current);current={};used=0
                    current.setdefault(path,{**source,'lines':[]})['lines'].append(row);used+=cost;seen_lines.add(key)
        if current:parts.append(current)
        for part in parts:
            visible={p:{l['line'] for l in src['lines']} for p,src in part.items()}
            nodes=[byid[r] for r in selected if any(byid[r]['start']<=l<=byid[r]['end'] for l in visible.get(byid[r]['path'],()))]
            ids={n['id'] for n in nodes}
            packages.append({'sources':part,'entry':byid[root],'frontier':frontier,
                'graph':{'nodes':nodes,'edges':[e for e in graph['edges'] if e['source'] in ids and e['target'] in ids],
                         'limits':['仅入口及直接实现；未展开引用列入frontier，不代表不存在业务步骤。']}})
    for i,p in enumerate(packages):p.update(continuation=i,definition_pages=len(packages))
    return packages


def source_excerpt(proof,anchors,limit=2400):
    """Select genuine nearby lines; original line numbers and hashes stay intact."""
    result={};used=0
    for path,line in anchors:
        source=proof.get(path)
        if not source:continue
        from .kd_s3_support import line_anchors
        points=line_anchors(line)
        candidates=[l for l in source['lines'] if any(abs(l['line']-n)<=6 for n in points)]
        for row in candidates:
            known={l['line'] for l in result.get(path,{}).get('lines',[])}
            if row['line'] in known:continue
            cost=len(row['text'])+1
            if used+cost>limit:continue
            result.setdefault(path,{**source,'lines':[]})['lines'].append(copy.deepcopy(row));used+=cost
    for s in result.values():s['lines'].sort(key=lambda l:l['line'])
    return result


def repair_package(package):
    """Always narrow actual visible source when possible; retain the remainder."""
    count=sum(len(s['lines']) for s in package['sources'].values())
    total=sum(len(l['text'])+1 for s in package['sources'].values() for l in s['lines'])
    pieces=split_sources(package['sources'],max(1,total//2))
    if len(pieces)==1 and count>1:
        left={};right={};n=0
        for p,s in package['sources'].items():
            for l in s['lines']:
                out=left if n<count//2 else right
                out.setdefault(p,{**s,'lines':[]})['lines'].append(copy.deepcopy(l));n+=1
        pieces=[left,right]
    return [{**copy.deepcopy(package),'sources':s,'repair_slice':i} for i,s in enumerate(pieces)]


def pair_sources(pair,state,graph,byid):
    """Read both endpoints' contract evidence plus actual handoff lines, not whole SOP dossiers."""
    parts=[]
    from .kd_s3_support import confirmed_roots
    owners={sid:confirmed_roots(state['accepted'][sid]['value'],byid.values()) for sid in pair}
    for sid in pair:
        value=state['accepted'][sid];other=next(s for s in pair if s!=sid)
        anchors=[]
        for e in graph['edges']:
            if e['source'] in owners[sid] and e['target'] in owners[other] and e['source'] in byid:
                anchors.append((byid[e['source']]['path'],e.get('line') or byid[e['source']]['start']))
        anchors.extend((e['path'],e['line']) for e in value['value'].get('evidence',[]) if e.get('target_id')==sid)
        anchors.extend((e['path'],e['line']) for e in value['value'].get('implementations',[]))
        selected=source_excerpt(value['proof'],anchors,4000)
        if not selected:
            pages=split_sources(value['proof'],4000);selected=pages[0] if pages else {}
        parts.append(selected)
    return merge_sources(*parts)
