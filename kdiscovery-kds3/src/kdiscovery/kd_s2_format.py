"""Requirement MRG validation; deliberately independent of the executable/UI MRG."""
import copy
import hashlib
import json
from pathlib import Path
import jsonschema

FORMAT = 'mrg-requirements-v1'


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def definition(workspace):
    path = Path(workspace) / 'mrg.format.json'
    raw = path.read_bytes()
    schema = json.loads(raw)
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema, digest(raw)


def validation_fingerprint(schema):
    """Documentation changes do not change validation; constraints do."""
    def clean(value, mapping=False):
        if isinstance(value, dict):
            if mapping: return {k: clean(v) for k, v in value.items()}
            return {k: clean(v, k in ('properties', '$defs', 'definitions', 'patternProperties', 'dependentSchemas'))
                    for k, v in value.items() if k not in ('description', 'title', '$comment', 'examples')}
        if isinstance(value, list): return [clean(v) for v in value]
        return value
    return digest(clean(schema))


def validate(mrg, schema):
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(mrg), key=lambda e: str(list(e.path)))
    if errors: raise ValueError('MRG 格式：' + str(list(errors[0].path)) + ' ' + errors[0].message)
    entities = [mrg['MNS']] + [v for k in ('SOP', 'OMN', 'MN', 'ME', 'Sessions', 'SE', 'business_objects') for v in mrg[k]]
    ids = [v['id'] for v in entities]
    if len(ids) != len(set(ids)): raise ValueError('MRG ID 重复')
    indexed = {v['id']: v for v in entities}
    sops = {v['id']: v for v in mrg['SOP']}
    nodes = {v['id']: v for k in ('OMN', 'MN') for v in mrg[k]}
    objects = {v['id'] for v in mrg['business_objects']}
    if set(mrg['MNS']['SOP_refs']) != {k for k, v in sops.items() if v['parent_sop_id'] is None}:
        raise ValueError('MNS 必须准确引用顶层功能')
    for sid, sop in sops.items():
        seen = {sid}; parent = sop['parent_sop_id']
        while parent is not None:
            if parent not in sops or parent in seen: raise ValueError('功能包含关系悬空或循环')
            seen.add(parent); parent = sops[parent]['parent_sop_id']
    for n in nodes.values():
        if n['sop_id'] not in sops: raise ValueError('内部步骤所属功能不存在')
    for v in list(sops.values()) + list(nodes.values()):
        for side in ('inputs', 'outputs'):
            keys = [p['key'] for p in v[side]]
            if len(keys) != len(set(keys)): raise ValueError('语义输入输出 key 重复')
            if any(p.get('object_ref') and p['object_ref'] not in objects for p in v[side]):
                raise ValueError('业务对象引用不存在')
    def port(nid, side, key):
        if nid not in indexed or not any(p['key'] == key for p in indexed[nid].get(side, [])):
            raise ValueError('交接引用不存在的语义输入输出：' + str(nid) + '/' + str(key))
    for sop in sops.values():
        for side, field, node_key in [('inputs', 'input_bindings', 'node_input_key'), ('outputs', 'output_bindings', 'node_output_key')]:
            for binding in sop[field]:
                if binding['node_id'] not in nodes or nodes[binding['node_id']]['sop_id'] != sop['id']:
                    raise ValueError('功能边界连接不能跨层')
                port(sop['id'], side, binding['input_key' if side == 'inputs' else 'output_key'])
                port(binding['node_id'], side, binding[node_key])
    forward = {}
    for edge in mrg['ME']:
        a, b, owner = edge['source'], edge['target'], edge['owner_sop_id']
        if a == b and edge['relation'] not in ('feedback', 'retry'): raise ValueError('只有有条件的反馈或重试可以自连')
        if edge['level'] == 'function':
            if a not in sops or b not in sops or sops[a]['parent_sop_id'] != owner or sops[b]['parent_sop_id'] != owner:
                raise ValueError('功能关系必须连接同一父流程的功能')
        elif a not in nodes or b not in nodes or owner not in sops or nodes[a]['sop_id'] != owner or nodes[b]['sop_id'] != owner:
            raise ValueError('内部关系不能跨层或跨功能')
        for t in edge['transfers']:
            port(a, 'outputs', t['output_key']); port(b, 'inputs', t['input_key'])
        if edge['relation'] in ('feedback', 'retry', 'conditional_next') and not edge['condition'].strip():
            raise ValueError('条件推进、反馈和重试必须说明业务条件')
        if edge['relation'] in ('delivery', 'conditional_next'):
            forward.setdefault(a, set()).add(b)
    visiting, done = set(), set()
    def visit(n):
        if n in visiting: raise ValueError('前向关系存在循环，循环应明确为反馈或重试')
        if n in done: return
        visiting.add(n)
        for b in forward.get(n, []): visit(b)
        visiting.remove(n); done.add(n)
    for n in list(forward): visit(n)
    sessions = {v['id'] for v in mrg['Sessions']}
    for s in mrg['Sessions']:
        if not set(s['node_refs']) <= nodes.keys(): raise ValueError('交互引用不存在的步骤')
    for e in mrg['SE']:
        if e['source'] not in sessions or e['target'] not in sessions: raise ValueError('界面关系引用不存在')
    for gap in mrg['open_items']:
        if gap['target_id'] not in indexed: raise ValueError('缺口指向不存在的对象')
    return mrg


def completeness(mrg):
    """Describe missing business links, without refusing a valid partial requirement."""
    gaps = []
    for sop in mrg['SOP']:
        nodes = [n for k in ('OMN', 'MN') for n in mrg[k] if n['sop_id'] == sop['id']]
        if not nodes: continue
        outputs = {b['output_key'] for b in sop['output_bindings']}
        for p in sop['outputs']:
            if p['key'] not in outputs:
                gaps.append({'target_id': sop['id'], 'topic': 'output_binding', 'status': 'unknown',
                    'description': '交付“' + p['meaning'] + '”尚未明确由哪个内部步骤产出', 'locators': []})
        supplied = {(b['node_id'], b['node_input_key']) for b in sop['input_bindings']}
        supplied.update((e['target'], t['input_key']) for e in mrg['ME'] if e['level'] == 'internal' and e['owner_sop_id'] == sop['id'] for t in e['transfers'])
        for n in nodes:
            for p in n['inputs']:
                if p['necessity'] == 'required' and (n['id'], p['key']) not in supplied:
                    gaps.append({'target_id': n['id'], 'topic': 'input_supply', 'status': 'unknown',
                        'description': '所需“' + p['meaning'] + '”尚未说明业务来源', 'locators': []})
    return gaps


def empty(overview):
    return {'format': FORMAT, 'MNS': copy.deepcopy(overview['MNS']),
        **{k: [] for k in ('SOP', 'OMN', 'MN', 'ME', 'Sessions', 'SE', 'business_objects', 'open_items')}}
