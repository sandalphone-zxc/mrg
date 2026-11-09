"""KN-S-1: versioned tree, weighted keyword and content-addressed vector index."""
import json
import numpy as np
from .knowledge import digest, encoded
from .knowledge_strategies import KIndex
from .retrieval import tokens, values
from .vector_index import valid_vector
from .providers import ProviderError


@KIndex.register
class HierarchicalIndex(KIndex):
    source = 'github'
    strategy = 'KN-S-1'
    description = '项目、各级业务 SOP 与实现单元的关键词/向量索引及父子回溯'

    def __init__(self, store, providers):
        self.store, self.providers = store, providers
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS kn_nodes(snapshot TEXT,node_id TEXT,kind TEXT,parent TEXT,project TEXT,
                    completeness INTEGER,specificity INTEGER,content_hash TEXT,metadata TEXT,
                    PRIMARY KEY(snapshot,node_id));
                CREATE TABLE IF NOT EXISTS kn_edges(snapshot TEXT,parent TEXT,child TEXT,PRIMARY KEY(snapshot,parent,child));
                CREATE VIRTUAL TABLE IF NOT EXISTS kn_search USING fts5(snapshot UNINDEXED,node_id UNINDEXED,
                    name,goal,scenario,ports,tags);
                CREATE TABLE IF NOT EXISTS kn_vectors(snapshot TEXT,node_id TEXT,model TEXT,content_hash TEXT,vector TEXT,
                    PRIMARY KEY(snapshot,node_id,model));
                CREATE TABLE IF NOT EXISTS kn_vector_cache(model TEXT,content_hash TEXT,vector TEXT,
                    PRIMARY KEY(model,content_hash));
            ''')

    @staticmethod
    def documents(snapshot):
        entities=snapshot['entities'];rows=snapshot['rows'];parents={};owners={}
        for key,project in snapshot['projects'].items():
            for root in project['mns'].get('SOP_refs',[]):
                owners[root]=key
                pending=[root]
                while pending:
                    sid=pending.pop()
                    for child in entities[sid].get('sub_sop_refs',[]):
                        if child in parents and parents[child]!=sid:raise ValueError('SOP 有多个父节点')
                        parents[child]=sid;owners[child]=key;pending.append(child)
        result=[]
        for sid,project in owners.items():
            sop=entities[sid];row=rows.get(sid,{})
            project_info=snapshot['projects'][project]
            profile=row.get('capability_profile') or {}
            details=profile.get('details',{})
            scenario=values(details.get('scenarios',[]))+' '+values(details.get('limitations',[]))
            inputs=row.get('inputs') or values([entities[n].get('inputs',[]) for n in sop.get('node_refs',[]) if n in entities])
            outputs=row.get('outputs') or values([entities[n].get('outputs',[]) for n in sop.get('node_refs',[]) if n in entities])
            tags=' '.join([row.get('industry',''),row.get('interface_kind',''),row.get('independence_level','')])
            evidence=len(row.get('functional_evidence',[]))
            completeness=min(3,int(bool(inputs and outputs))+int(bool(sop.get('entry_conditions') and sop.get('completion_conditions')))+int(bool(evidence)))
            specificity=min(3,len(details.get('scenarios',[]))+len(details.get('limitations',[])))
            result.append({'id':sid,'kind':'feature' if sid in rows else 'root','parent':parents.get(sid),
                'project':project,'name':sop['name'],'aliases':[a for a in row.get('aliases',[]) if isinstance(a,str)],
                'goal':sop['goal'],'scenario':scenario.strip(),
                'ports':str(inputs)+' '+str(outputs),'tags':tags.strip(),'completeness':completeness,
                'specificity':specificity,'evidence_level':min(3,1+evidence) if evidence else 0,
                'runtime_verified':bool(row.get('runtime_verified',False)),
                'code_status':row.get('mapping_status','unmapped'),
                'license':project_info.get('license'),'commit':project_info.get('commit') or
                    next((c.get('commit') for c in row.get('code_modules',[]) if c.get('commit')),None)})
        for project,tree in snapshot.get('trees',{}).items():
            for unit in tree.get('nodes',[]):
                if unit['type']!='unit':continue
                result.append({'id':unit['id'],'kind':'unit','parent':unit['parent'],'project':project,
                    'name':unit['name'],'goal':unit['purpose'],'scenario':' '.join(unit.get('preconditions',[])),
                    'ports':' '.join(unit.get('inputs',[])+unit.get('outputs',[])),
                    'tags':'实现单元','completeness':min(3,int(bool(unit.get('inputs') and unit.get('outputs')))+int(bool(unit.get('steps')))),
                    'specificity':min(3,len(unit.get('preconditions',[]))),
                    'evidence_level':unit['confidence'],'runtime_verified':False,
                    'code_status':'source_located_not_runtime_tested' if unit.get('code_locations') else 'unmapped',
                    'license':snapshot['projects'][project].get('license'),'commit':tree['commit']})
        ids=[n['id'] for n in result]
        if len(ids)!=len(set(ids)):raise ValueError('分层索引节点重复')
        return result

    def build(self, snapshot, progress=None):
        docs=self.documents(snapshot);sid=snapshot['id']
        hashes={d['id']:digest(encoded([self.strategy,d['name'],d.get('aliases',[]),d['goal'],d['scenario'],d['ports'],d['tags']]).encode()) for d in docs}
        with self.store.connect() as db:
            existing={r['node_id']:r['content_hash'] for r in db.execute('SELECT node_id,content_hash FROM kn_nodes WHERE snapshot=?',(sid,))}
        if existing!=hashes:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM kn_nodes WHERE snapshot=?',(sid,))
                db.execute('DELETE FROM kn_edges WHERE snapshot=?',(sid,))
                db.execute('DELETE FROM kn_search WHERE snapshot=?',(sid,))
                db.executemany('INSERT INTO kn_nodes VALUES(?,?,?,?,?,?,?,?,?)',[(sid,d['id'],d['kind'],d['parent'],d['project'],
                    d['completeness'],d['specificity'],hashes[d['id']],encoded(d)) for d in docs])
                db.executemany('INSERT INTO kn_edges VALUES(?,?,?)',[(sid,d['parent'],d['id']) for d in docs if d['parent']])
                db.executemany('INSERT INTO kn_search VALUES(?,?,?,?,?,?,?)',[(sid,d['id'],
                    ' '.join(tokens(d['name']+' '+' '.join(d.get('aliases',[])))),' '.join(tokens(d['goal'])),' '.join(tokens(d['scenario'])),
                    ' '.join(tokens(d['ports'])),' '.join(tokens(d['tags']))) for d in docs])
        result={'snapshot':sid,'strategy':self.strategy,'nodes':len(docs),'keyword_ready':True,
                'vectors_ready':False,'embedded':0,'reused':0}
        if not self.providers.status().get('embedding_configured'):return result
        model=self.providers.vector_identity()
        with self.store.connect() as db:
            old={r['node_id']:r for r in db.execute('SELECT node_id,content_hash,vector FROM kn_vectors WHERE snapshot=? AND model=?',(sid,model))}
            cache={r['content_hash']:r['vector'] for r in db.execute('SELECT content_hash,vector FROM kn_vector_cache WHERE model=?',(model,))}
        unique={hashes[d['id']]:d for d in docs}
        vectors={h:cache[h] for h in unique if h in cache}
        pending=[h for h in unique if h not in vectors]
        for offset in range(0,len(pending),24):
            keys=pending[offset:offset+24]
            texts=[' '.join(str(unique[h][field]) for field in ('name','aliases','goal','scenario','ports','tags') if field in unique[h]) for h in keys]
            values_out=self.providers.embed(texts)
            if len(values_out)!=len(keys) or not all(valid_vector(v) for v in values_out):raise ValueError('分层向量结果无效')
            with self.store.connect() as db:
                db.executemany('INSERT OR REPLACE INTO kn_vector_cache VALUES(?,?,?)',[(model,h,json.dumps(v)) for h,v in zip(keys,values_out)])
            vectors.update((h,json.dumps(v)) for h,v in zip(keys,values_out))
            if progress:progress(min(offset+24,len(pending)),len(pending))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for d in docs:
                h=hashes[d['id']]
                if d['id'] not in old or old[d['id']]['content_hash']!=h:
                    db.execute('INSERT OR REPLACE INTO kn_vectors VALUES(?,?,?,?,?)',(sid,d['id'],model,h,vectors[h]))
            for stale in old.keys()-hashes.keys():db.execute('DELETE FROM kn_vectors WHERE snapshot=? AND node_id=? AND model=?',(sid,stale,model))
        result.update(vectors_ready=True,embedded=len(pending),reused=len(docs)-len(pending))
        return result

    def search(self, snapshot, query, limit=12, include_units=False, min_completeness=0, max_specificity=3,
               use_vectors=True, require_code=False, license_id=None):
        terms=tokens(query)[:60]
        if not terms:return []
        match=' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
        with self.store.connect() as db:
            rows=db.execute('''SELECT n.metadata,bm25(kn_search,0,0,6,4,2,2,1) AS rank FROM kn_search
                JOIN kn_nodes n ON n.snapshot=kn_search.snapshot AND n.node_id=kn_search.node_id
                WHERE kn_search.snapshot=? AND kn_search MATCH ? AND n.completeness>=? AND n.specificity<=?
                ORDER BY rank LIMIT ?''',(snapshot,match,min_completeness,max_specificity,limit*3)).fetchall()
        scored={}
        for rank,row in enumerate(rows):
            item=json.loads(row['metadata'])
            if item['kind']=='unit' and not include_units:continue
            if require_code and item['code_status']=='unmapped':continue
            if license_id and item.get('license')!=license_id:continue
            terms_set=set(terms)
            hits=[label for label,value in [('名称／别名',item['name']+' '+' '.join(item.get('aliases',[]))),
                  ('目标',item['goal']),('场景',item['scenario']),('输入输出',item['ports']),('标签',item['tags'])]
                  if terms_set & set(tokens(value))]
            scored[item['id']]={'item':item,'score':1/(20+rank),'evidence':hits or ['关键词命中']}
        if use_vectors and self.providers.status().get('embedding_configured'):
            model=self.providers.vector_identity()
            with self.store.connect() as db:
                vectors=db.execute('''SELECT n.metadata,v.vector FROM kn_vectors v JOIN kn_nodes n
                    ON n.snapshot=v.snapshot AND n.node_id=v.node_id WHERE v.snapshot=? AND v.model=?''',(snapshot,model)).fetchall()
            try:
                query_vector=np.asarray(self.providers.embed([query])[0],dtype=float)
                for row in vectors:
                    item=json.loads(row['metadata'])
                    if item['kind']=='unit' and not include_units:continue
                    if item['completeness']<min_completeness or item['specificity']>max_specificity:continue
                    if require_code and item['code_status']=='unmapped':continue
                    if license_id and item.get('license')!=license_id:continue
                    vector=np.asarray(json.loads(row['vector']),dtype=float)
                    if vector.shape!=query_vector.shape:continue
                    similarity=float(vector@query_vector/(np.linalg.norm(vector)*np.linalg.norm(query_vector)))
                    if not np.isfinite(similarity):continue
                    entry=scored.setdefault(item['id'],{'item':item,'score':0,'evidence':[]})
                    entry['score']+=max(0,similarity)*0.04
                    entry['evidence'].append('语义相似')
            except (ProviderError,ValueError,IndexError,TypeError):pass
        return [{**value['item'],'score':round(value['score'],6),'match_evidence':value['evidence']}
                for value in sorted(scored.values(),key=lambda x:-x['score'])[:limit]]

    def relatives(self, snapshot, node_id, direction='parents'):
        if direction not in ('parents','children'):raise ValueError('关系方向无效')
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM kn_nodes WHERE snapshot=? AND node_id=?',(snapshot,node_id)).fetchone():raise LookupError('索引节点不存在')
            field,other=('child','parent') if direction=='parents' else ('parent','child')
            rows=db.execute(f'''WITH RECURSIVE walk(id,depth) AS (
                SELECT {other},1 FROM kn_edges WHERE snapshot=? AND {field}=?
                UNION ALL SELECT e.{other},w.depth+1 FROM kn_edges e JOIN walk w ON e.{field}=w.id
                WHERE e.snapshot=? AND w.depth<100)
                SELECT n.metadata,w.depth FROM walk w JOIN kn_nodes n ON n.snapshot=? AND n.node_id=w.id
                ORDER BY w.depth,n.node_id''',(snapshot,node_id,snapshot,snapshot)).fetchall()
        return [{**json.loads(r['metadata']),'distance':r['depth']} for r in rows]
