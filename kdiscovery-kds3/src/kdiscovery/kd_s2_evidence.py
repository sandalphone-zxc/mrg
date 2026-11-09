"""Persistable semantic windows, independent of a repository's business domain."""
import re
from pathlib import PurePosixPath
from .kd_s2_format import digest
from .kd_s2_units import split_sources


def terms(values):
    text=' '.join(str(v) for v in values)
    text=re.sub(r'([a-z])([A-Z])',r'\1 \2',text)
    return set(re.findall(r'[\w-]{3,}',text.lower()))-{'src','lib','services','service','modules','packages','index','main','js','json','typescript'}


def plan(materials, feature, limit=8000):
    """Keep all selected definition chunks, including the body beyond line 200.

    A page is evidence, not a newly invented function. Candidate scope and
    page coverage are tracked independently by the scheduler.
    """
    hints=materials.normalize_hints(feature['locators'])
    paths={e['path'] for e in materials.tree}
    explicit=[p for p in hints if p in paths]
    roots=list(dict.fromkeys(explicit+materials.select(hints)[:3]))
    followed=materials.follow(roots,depth=2)
    materials.scan(followed)
    wanted=terms(hints+[feature['key'],feature['name']])
    queues=[];seen=set()
    for path in followed:
        f=materials.read(path)
        if not f:continue
        lines=f['lines'];index=materials.architecture.get(path,{})
        defs=index.get('definitions',[])
        # A class wrapper must not eclipse the individual methods within it.
        defs=[d for d in defs if not any(x is not d and d['start']<x['start'] and x['end']<d['end'] for x in defs)]
        entry_text=' '.join(e['symbol'] for e in index.get('entries',[]))
        exported=set(re.findall(r'\b(?:export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const)|exports\.)\s*(\w+)', '\n'.join(lines)))
        for match in re.finditer(r'(?:module\.exports\s*=|export)\s*\{([^}]+)\}', '\n'.join(lines)):
            exported.update(re.findall(r'\b\w+\b',match[1]))
        text='\n'.join(lines);default_refs=set()
        for match in re.finditer(r'\bexport\s+default\b|\bmodule\.exports\s*=',text):
            stop=re.search(r'\nexport\s',text[match.end():])
            body=text[match.end():match.end()+stop.start() if stop else min(len(text),match.end()+8000)]
            default_refs.update(d['name'] for d in defs if re.search(r'\b'+re.escape(d['name'])+r'\b',body))
        def score(d):
            body='\n'.join(lines[d['start']-1:d['end']])
            public=d['name'] in exported or (path.endswith('.py') and not d['name'].startswith('_'))
            return (6*public+24*(d['name'] in default_refs)+32*(d['name'] in hints)+8*(d['name'] in entry_text)+4*len(terms([d['name']])&wanted)
                    +min(4,len(re.findall(r'\b(return|throw|raise|commit|rollback|save|insert|update)\b',body))))
        spans=[(d['start']-1,min(d['end'],len(lines)),d['name']) for d in sorted(defs,key=lambda d:(-score(d),d['start']))]
        if not spans:
            # Documents use complete sections; unparsed languages retain every
            # line in resumable chunks instead of treating a prefix as coverage.
            starts=[i for i,l in enumerate(lines) if re.match(r'^#{1,6}\s+',l)]
            starts=sorted(set([0]+starts));spans=[(a,starts[i+1] if i+1<len(starts) else len(lines),'section') for i,a in enumerate(starts)]
        else:
            # Imports, anonymous exports and unparsed syntax are not silently
            # labelled checked merely because some definitions were recognized.
            covered={i for a,b,_ in spans for i in range(a,b)}
            start=None
            for i in range(len(lines)+1):
                if i<len(lines) and i not in covered:
                    if start is None:start=i
                elif start is not None:
                    spans.append((start,i,'unparsed_or_context'));start=None
        chunks=[]
        for start,end,symbol in spans:
            if end<=start:continue
            source={k:f[k] for k in ('sha256','kind','representation')}
            source['lines']=[{'line':i+1,'text':lines[i]} for i in range(start,end)]
            for part in split_sources({path:source},max(512,limit//2)):
                key=digest([path,f['sha256'],[l['line'] for l in part[path]['lines']]])
                if key in seen:continue
                seen.add(key);chunks.append({'id':key,'path':path,'symbol':symbol,'proof':part})
        if chunks:queues.append(chunks)
    # Every primary/directly referenced file gets a first definition before
    # consuming the tail of one long file. Later chunks remain explicit tasks.
    ordered=[q[i] for i in range(max((len(q) for q in queues),default=0)) for q in queues if i<len(q)]
    pages=[];proof={};ids=[];size=0
    for chunk in ordered:
        cost=sum(len(l['text'])+1 for s in chunk['proof'].values() for l in s['lines'])
        if proof and size+cost>limit:pages.append({'proof':proof,'chunks':ids});proof={};ids=[];size=0
        proof=merge_sources(proof,chunk['proof']);ids.append({k:v for k,v in chunk.items() if k!='proof'});size+=cost
    if proof:pages.append({'proof':proof,'chunks':ids})
    return {'feature':feature,'pages':pages,'paths':followed,'limit':limit,
        'rule':'definition-windows-v1','note':'未查看的页仍是待取证，不是能力不存在。'}


def merge_sources(*groups):
    merged={}
    for group in groups:
        for path,s in group.items():
            old=merged.get(path,{**s,'lines':[]})
            if old['sha256']!=s['sha256']:raise ValueError('同一路径出现不同来源版本')
            merged[path]={**old,'lines':sorted({l['line']:l for l in old['lines']+s['lines']}.values(),key=lambda l:l['line'])}
    return merged


def fair_features(features, materials):
    """Round-robin actual directory modules; the directory is not a capability."""
    from .kd_s2_architecture import module_key
    paths={e['path'] for e in materials.tree};queues={}
    for f in features:
        path=next((p for p in materials.normalize_hints(f['locators']) if p in paths),None)
        key=module_key(path) if path else f['key']
        queues.setdefault(key,[]).append(f)
    return [q[i] for i in range(max((len(q) for q in queues.values()),default=0)) for q in queues.values() if i<len(q)]
