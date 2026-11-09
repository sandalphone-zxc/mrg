"""Durable evidence cursors and additive, evidence-preserving capability updates."""
import copy
from .kd_s2_format import digest


def merge_increment(base, extra):
    """Keep reviewed facts; append proven array facts with relocated evidence.

    A continuation is explicitly constrained to the same capability. Conflicting
    port keys remain a gap rather than silently replacing an existing contract.
    """
    result=copy.deepcopy(base);old=result['mrg']['SOP'][0];new=extra['mrg']['SOP'][0]
    maps={};conflicts=[]
    for field in ('inputs','outputs','rules','preconditions','completion_conditions','exceptions'):
        maps[field]={}
        for i,value in enumerate(new[field]):
            if value in old[field]:j=old[field].index(value)
            elif field in ('inputs','outputs') and any(v['key']==value['key'] for v in old[field]):
                conflicts.append({'field':field,'value':value});continue
            else:j=len(old[field]);old[field].append(copy.deepcopy(value))
            maps[field][i]=j
    for e in extra['evidence']:
        if e['target_id']!=new['id']:continue
        parts=e['field'].split('/')
        if parts[0] not in maps or len(parts)<2:continue
        if not parts[1].isdigit() or int(parts[1]) not in maps[parts[0]]:continue
        parts[1]=str(maps[parts[0]][int(parts[1])]);entry=copy.deepcopy(e)
        entry['field']='/'.join(parts)
        if any(all(v.get(k)==entry.get(k) for k in ('target_id','field','path','line','quote')) for v in result['evidence']):continue
        entry['id']=old['id']+'.proof.'+digest(entry)[:14]
        if entry not in result['evidence']:
            result['evidence'].append(entry);old['source_refs'].append(entry['id'])
    for field in ('implementations','discovered_features','pending_relations'):
        for v in extra.get(field,[]):
            if v not in result.setdefault(field,[]):result[field].append(copy.deepcopy(v))
    for item in extra['mrg']['open_items']:
        if item not in result['mrg']['open_items']:result['mrg']['open_items'].append(item)
    for conflict in conflicts:
        result['mrg']['open_items'].append({'target_id':old['id'],'topic':'conflicting_contract','status':'conflicting',
            'description':'后续材料对相同端口键给出不同定义，保留已复核定义并待核对：'+str(conflict),'locators':[]})
    result['coverage']=extra.get('coverage',{})
    return result


def scope_status(value, pages_read, pages_total):
    scope=value.get('coverage',{})
    complete=(scope.get('relation')=='same' and not scope.get('remaining') and pages_read>=pages_total)
    return {'contract_status':'verified','scope_status':'covered' if complete else 'partial',
            'scope_claim':scope,'pages_read':pages_read,'pages_total':pages_total}


def merge_details(base, extra):
    """Append reviewed internal deltas; never replace prior confirmed steps."""
    result=copy.deepcopy(base);m=result['mrg'];new=extra['mrg'];conflicts=set();accepted_ids=set()
    for category in ('OMN','MN','ME'):
        existing={n['id']:n for n in m[category]}
        for node in new[category]:
            if category=='ME' and (node['source'] in conflicts or node['target'] in conflicts):continue
            if node['id'] in existing and existing[node['id']]!=node:
                conflicts.add(node['id']);continue
            if node['id'] not in existing:m[category].append(copy.deepcopy(node))
            accepted_ids.add(node['id'])
    for field in ('input_bindings','output_bindings'):
        for binding in new['SOP'][0][field]:
            if binding['node_id'] not in conflicts and binding not in m['SOP'][0][field]:m['SOP'][0][field].append(copy.deepcopy(binding))
    for e in extra['evidence']:
        if e['target_id']!=m['SOP'][0]['id']:continue
        parts=e['field'].split('/')
        if len(parts)<2 or parts[0] not in ('input_bindings','output_bindings') or not parts[1].isdigit():continue
        try:binding=new['SOP'][0][parts[0]][int(parts[1])]
        except IndexError:continue
        if binding not in m['SOP'][0][parts[0]]:continue
        parts[1]=str(m['SOP'][0][parts[0]].index(binding));entry=copy.deepcopy(e);entry['field']='/'.join(parts)
        if any(all(v.get(k)==entry.get(k) for k in ('target_id','field','path','line','quote')) for v in result['evidence']):continue
        entry['id']=entry['target_id']+'.binding-proof.'+digest(entry)[:14]
        result['evidence'].append(entry);m['SOP'][0]['source_refs'].append(entry['id'])
    for e in extra['evidence']:
        if e['target_id'] not in accepted_ids:continue
        existing=next((v for v in result['evidence'] if v['id']==e['id']),None)
        if existing:
            if any(existing.get(k)!=e.get(k) for k in ('target_id','field','path','line','quote')):
                m['open_items'].append({'target_id':m['SOP'][0]['id'],'topic':'evidence_id_conflict','status':'conflicting',
                    'description':'同一证据ID对应不同事实，保留原证据并待核对：'+e['id'],'locators':[e.get('path','')]})
            continue
        result['evidence'].append(copy.deepcopy(e))
    for e in extra['implementations']:
        if e['target_id'] in accepted_ids and e not in result['implementations']:result['implementations'].append(copy.deepcopy(e))
    for gap in new['open_items']:
        if gap['target_id']==m['MNS']['id'] and gap['topic']=='project_evidence' and m['MNS']['source_refs']:continue
        if gap not in m['open_items']:m['open_items'].append(copy.deepcopy(gap))
    for nid in conflicts:
        m['open_items'].append({'target_id':m['SOP'][0]['id'],'topic':'internal_step_conflict','status':'conflicting',
            'description':'后续步骤使用已存在的ID但定义不同，保留原步骤并待核对：'+nid,'locators':[]})
    return result
