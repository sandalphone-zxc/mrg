import copy,json
from .kd_s2 import check_evidence
from .kd_s2_enrichment import bind_relation_evidence

def assert_preserved(base, after):
    """An enrichment may append facts, not silently lose/change accepted ones."""
    b, a = base['mrg'], after['mrg']
    if {s['id'] for s in a['SOP']} != {s['id'] for s in b['SOP']}:
        raise ValueError('补充不能新增或删除原功能')
    for key,value in b['MNS'].items():
        if key != 'SOP_refs' and a['MNS'].get(key) != value:
            raise ValueError('补充不能改写原项目事实：'+key)
    for old in b['SOP']:
        new=next(s for s in a['SOP'] if s['id']==old['id'])
        for key,value in old.items():
            if key=='parent_sop_id' and value is None:continue
            if isinstance(value,list):
                if any(v not in new.get(key,[]) for v in value):raise ValueError('已有SOP事实丢失：'+old['id']+'/'+key)
            elif new.get(key)!=value:raise ValueError('已有SOP定义改变：'+old['id']+'/'+key)
    for category in ('OMN','MN','ME','Sessions','SE','business_objects'):
        for old in b[category]:
            if old not in a[category]:raise ValueError('已有节点/关系被改写：'+old['id'])
    for field in ('evidence','implementations'):
        if any(v not in after[field] for v in base[field]):raise ValueError('已有来源/实现依据丢失：'+field)


class Supplement:
    @staticmethod
    def apply_relations(value,relation,reviewed,group,proof,schema):
        relation=bind_relation_evidence(relation)
        result=copy.deepcopy(value);removed=copy.deepcopy(reviewed['drop_edges'])
        dropped={e['id'] for e in reviewed['drop_edges']}
        for edge in relation.get('ME',[]):
            if edge.get('id') in dropped:continue
            try:
                if edge.get('source') not in group or edge.get('target') not in group or edge.get('level')!='function':
                    raise ValueError('关系不在本包功能层范围')
                # Avoid duplicate edges generated in overlapping evidence groups.
                signature=lambda e: tuple(json.dumps(e.get(k),sort_keys=True,ensure_ascii=False) for k in ('source','target','relation','condition','transfers'))
                if any(signature(e)==signature(edge) for e in result['mrg']['ME']):continue
                candidate=copy.deepcopy(result);candidate['mrg']['ME'].append(edge)
                candidate['evidence'] += [e for e in relation.get('evidence',[]) if e.get('target_id')==edge['id']]
                preserved=copy.deepcopy(candidate['implementations'])
                check_evidence(candidate,proof,schema);candidate['implementations']=preserved;candidate['mrg']['MNS']={**copy.deepcopy(result['mrg']['MNS']),'SOP_refs':candidate['mrg']['MNS']['SOP_refs']}
                old_records={e['id']:e for e in result['evidence']}
                candidate['evidence']=[copy.deepcopy(old_records.get(e['id'],e)) for e in candidate['evidence']]
                for e in result['evidence']:
                    if not any(v['id']==e['id'] for v in candidate['evidence']):candidate['evidence'].append(copy.deepcopy(e))
                assert_preserved(result,candidate);result=candidate
            except (ValueError,KeyError,TypeError,IndexError) as exc:
                removed.append({'id':edge.get('id'),'reason':str(exc),'phase':'relations'})
        # Preserve original containment; new parents require direct reviewed evidence.
        rejected={p['child_id'] for p in reviewed.get('drop_parents',[])}
        for parent in relation.get('parents',[]):
            child,ancestor=parent.get('child_id'),parent.get('parent_id')
            if child in rejected or child not in group or ancestor not in group:continue
            try:
                candidate=copy.deepcopy(result);sop=next(s for s in candidate['mrg']['SOP'] if s['id']==child)
                if sop['parent_sop_id'] is not None:continue
                ev=[e for e in relation.get('evidence',[]) if e.get('target_id')==child and e.get('field')=='parent_sop_id']
                if not ev:raise ValueError('功能归属缺少直接证据')
                sop['parent_sop_id']=ancestor;sop['source_refs'] += [e['id'] for e in ev];candidate['evidence']+=ev
                candidate['mrg']['MNS']['SOP_refs']=[s['id'] for s in candidate['mrg']['SOP'] if s['parent_sop_id'] is None]
                preserved=copy.deepcopy(candidate['implementations'])
                check_evidence(candidate,proof,schema);candidate['implementations']=preserved;candidate['mrg']['MNS']={**copy.deepcopy(result['mrg']['MNS']),'SOP_refs':candidate['mrg']['MNS']['SOP_refs']}
                old_records={e['id']:e for e in result['evidence']}
                candidate['evidence']=[copy.deepcopy(old_records.get(e['id'],e)) for e in candidate['evidence']]
                for e in result['evidence']:
                    if not any(v['id']==e['id'] for v in candidate['evidence']):candidate['evidence'].append(copy.deepcopy(e))
                assert_preserved(result,candidate);result=candidate
            except (ValueError,KeyError,TypeError,StopIteration) as exc:removed.append({'id':child,'reason':str(exc),'phase':'hierarchy'})
        return result,removed
