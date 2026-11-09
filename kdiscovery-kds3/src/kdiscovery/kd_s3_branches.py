"""Alternative business paths inside one stable functional SOP, not extra graph nodes."""
import copy
import html
from .kd_s2_format import digest
from .kd_s2_units import canonical_field

INSTRUCTION='''
采用一个整体业务功能SOP，内部按有据业务路径分支表达；同一功能的不同入口不拆成互不相干的SOP。
sop.name/purpose始终表达feature所指的整体业务目标，不用当前分支名称取代整体名称。只确认读到的范围；未读分支写gaps，不声称已实现。
每包返回branch:{key,name,trigger,inputs:[],outputs:[],preconditions:[],rules:[],completion_conditions:[],exceptions:[]}。
branch是本包业务路径，不是SOP/MN/OMN节点。key参考known_branches保持稳定；续读同一分支沿用key。
分支触发、契约和完成条件只放branch，不放全功能共同约束；真正适用所有分支的事实才放sop/contract_additions。
分支证据target:"branch",field:"trigger"或"inputs/0"等；整体purpose证据target:"sop"，必须来自实际sources，不能引用feature.goal。
本分支必要输入可标required，程序会转换为整体SOP中带适用范围的端口；不能要求每个分支都提供其他分支的输入或同时完成其他分支交付。
steps/states/links只描述该分支实际操作。明确的其他分支可放后续取证线索，不把分支之间默认串联，也不虚构总调度节点。
内部端口可用本分支已定义的端口key字符串引用以减少重复，程序展开定义；步骤purpose和关系仍须给独立来源。
初次sop只给整体name/purpose及确属共同的事实；后续不重写整体goal，不使用scope_extension来把目标改成当前分支。
仅JSON，省略空数组、重复解释和代码细节。没有交接依据时省略links，不进行多轮推理猜测。
'''


def collect_evidence(raw):
    """Accept equivalent per-object evidence without inventing a source or field."""
    value=copy.deepcopy(raw);out=[];seen=set()
    owners=[(value,None)]+[(value.get(k),k) for k in ('sop','branch','contract_additions')]
    owners += [(n,n.get('key')) for kind in ('steps','states','links') for n in value.get(kind,[]) if isinstance(n,dict)]
    for obj,owner in owners:
        if not isinstance(obj,dict):continue
        entries=obj.pop('evidence',[])
        if not isinstance(entries,list):
            value.setdefault('gaps',[]).append('证据字段不是数组，保留待核对：'+str(owner));continue
        for entry in entries:
            if not isinstance(entry,dict):
                value.setdefault('gaps',[]).append('证据条目不是对象，保留待核对：'+str(owner));continue
            entry=copy.deepcopy(entry)
            if owner:entry.setdefault('target',owner)
            signature=digest(entry)
            if signature not in seen:seen.add(signature);out.append(entry)
    value['evidence']=out
    return value


def prepare_branch(raw, base=None):
    """Compile explicitly scoped facts to existing semantic fields, preserving citations."""
    value=collect_evidence(raw);branch=value.get('branch')
    if not isinstance(branch,dict):
        value.setdefault('gaps',[]).append('本包未记录明确业务分支，分支归属尚未确认。')
        return value
    if not all(isinstance(branch.get(k),str) and branch[k].strip() for k in ('key','name')):
        value.setdefault('gaps',[]).append('分支key/name缺失，未采用未确定归属的步骤。')
        value['steps']=[];value['states']=[];value['links']=[]
        return value
    key=branch['key'];prefix='branch.'+digest(key)[:10]+'.';label='【'+branch['name']+'分支】'
    evidence=[]
    for e in value.get('evidence',[]):
        e=copy.deepcopy(e)
        if e.get('target')=='contract_additions':e.update(target='sop',field='contract_additions/'+canonical_field(e.get('field','')))
        evidence.append(e)
    value['evidence']=evidence
    target=value.setdefault('contract_additions',{}) if base else value.setdefault('sop',{})
    if not isinstance(target,dict):raise ValueError('分支的共同契约必须为对象')
    ports={};fields={};branch_proofs={}
    for field in ('inputs','outputs','preconditions','rules','completion_conditions','exceptions'):
        items=branch.get(field,[]) or []
        if not isinstance(items,list):
            value.setdefault('gaps',[]).append('分支字段不是数组：'+field);continue
        output=target.setdefault(field,[])
        for i,item in enumerate(items):
            local=copy.deepcopy(item)
            if field in ('inputs','outputs'):
                if not isinstance(local,dict) or not local.get('key'):
                    value.setdefault('gaps',[]).append('分支端口定义不完整：'+field+'/'+str(i));continue
                ports[(field,local['key'])]=(copy.deepcopy(local),i)
                necessity=local.get('necessity','unknown')
                local.update(key=prefix+local['key'],meaning=label+local.get('meaning','')+'；本分支必要性：'+necessity,
                             necessity='optional' if necessity in ('required','optional') else 'unknown')
            elif field=='exceptions':
                if not isinstance(local,dict):continue
                local['condition']=label+local.get('condition','')
            elif isinstance(local,str):local=label+local
            else:
                value.setdefault('gaps',[]).append('分支约束定义不完整：'+field+'/'+str(i));continue
            index=len(output);output.append(local)
            fields[f'{field}/{i}']=('contract_additions/' if base else '')+f'{field}/{index}'
            branch_proofs[(field,i)]=[e for e in evidence if e.get('target')=='branch' and canonical_field(e.get('field',''))==f'{field}/{i}']
    # A trigger is a business rule only if the caller supplied actual evidence.
    trigger_proof=[e for e in evidence if e.get('target')=='branch' and e.get('field')=='trigger']
    if branch.get('trigger') and trigger_proof:
        rules=target.setdefault('rules',[]);fields['trigger']=('contract_additions/' if base else '')+f'rules/{len(rules)}'
        rules.append(label+'触发：'+branch['trigger'])
    elif branch.get('trigger'):
        value.setdefault('gaps',[]).append('分支触发条件缺少定位，仅保留待确认线索：'+branch['trigger'])
    aliases={n['key']:prefix+n['key'] for field in ('steps','states','links') for n in value.get(field,[]) if isinstance(n,dict) and n.get('key')}
    inherited=[]
    for field in ('steps','states'):
        for node in value.get(field,[]):
            old_key=node['key'];node['key']=aliases[old_key];node['name']=label+node['name']
            for side in ('inputs','outputs'):
                resolved=[]
                for i,port in enumerate(node.get(side,[])):
                    if isinstance(port,str):
                        source_side=side if (side,port) in ports else 'inputs' if ('inputs',port) in ports else 'outputs'
                        source=ports.get((source_side,port))
                        if not source:
                            value.setdefault('gaps',[]).append('未定义的分支端口引用：'+port);continue
                        port=copy.deepcopy(source[0])
                        for e in branch_proofs.get((source_side,source[1]),[]):
                            inherited.append({**e,'target':old_key,'field':side+'/'+str(len(resolved))})
                    resolved.append(port)
                node[side]=resolved
    for edge in value.get('links',[]):
        edge['key']=aliases[edge['key']]
        for endpoint in ('source','target'):edge[endpoint]=aliases.get(edge[endpoint],edge[endpoint])
    for side in ('input','output'):
        for binding in value.get(side+'_bindings',[]):
            binding[side+'_key']=prefix+binding[side+'_key']
            binding['step']=aliases.get(binding['step'],binding['step'])
            binding['meaning']=label+binding.get('meaning','')
    value['evidence']=[]
    for e in evidence+inherited:
        if e.get('target')=='branch':
            mapped=fields.get(canonical_field(e.get('field','')))
            if mapped:value['evidence'].append({**e,'target':'sop','field':mapped})
        else:value['evidence'].append({**e,'target':aliases.get(e.get('target'),e.get('target'))})
    for e in value.get('implementations',[]):e['target']=aliases.get(e.get('target'),e.get('target'))
    uncertainties=[]
    for e in value.get('uncertainties',[]):
        if e.get('target')=='branch':
            field=fields.get(canonical_field(e.get('field','')))
            if field:
                e.update(target='sop',field=field)
                uncertainties.append(e)
            else:value.setdefault('gaps',[]).append('分支局部疑点未对应已发布字段：'+str(e))
        else:
            e['target']=aliases.get(e.get('target'),e.get('target'));uncertainties.append(e)
    value['uncertainties']=uncertainties
    value['branch_record']={'key':key,'name':branch['name'],'trigger':branch.get('trigger',''),
        'trigger_supported':bool(trigger_proof),'step_keys':[n['key'] for field in ('steps','states') for n in value.get(field,[])],
        'status':'partial','note':'仅代表已读取分支；其余路径和全局覆盖见缺口。'}
    # The broad contract is stable; optional scope proposals cannot rename it.
    if value.pop('scope_extension',None):value.setdefault('gaps',[]).append('忽略整体范围重写建议；按当前整体功能记录分支，不改为局部目标。')
    return value


def carry_existing_nodes(draft, base):
    """Existing nodes are context for a newly evidenced cross-page internal edge."""
    for kind in ('OMN','MN','ME'):
        ids={n['id'] for n in draft['mrg'][kind]}
        draft['mrg'][kind]+=copy.deepcopy([n for n in base['mrg'][kind] if n['id'] not in ids])
    existing={n['id'] for kind in ('OMN','MN','ME') for n in base['mrg'][kind]}
    seen={e['id'] for e in draft['evidence']}
    draft['evidence']+=copy.deepcopy([e for e in base['evidence'] if e['target_id'] in existing and e['id'] not in seen])


def attach_branch(value,raw):
    branch=raw.get('branch_record')
    if not branch:return
    sid=value['mrg']['SOP'][0]['id'];branch=copy.deepcopy(branch)
    live={n['id'] for kind in ('OMN','MN') for n in value['mrg'][kind]}
    branch['sop_id']=sid
    rules=value['mrg']['SOP'][0]['rules'];trigger='【'+branch['name']+'分支】触发：'+branch.get('trigger','')
    branch['trigger_supported']=trigger in rules and any(e['target_id']==sid and e['field']==f'rules/{rules.index(trigger)}' for e in value['evidence'])
    branch['node_ids']=[sid+'.'+kind+'.'+digest(k)[:10] for k in branch.pop('step_keys') for kind in ('OMN','MN') if sid+'.'+kind+'.'+digest(k)[:10] in live]
    value['branches']=[branch]


def merge_branches(result,extra):
    for incoming in extra.get('branches',[]):
        prior=next((b for b in result.setdefault('branches',[]) if b['key']==incoming['key']),None)
        if prior:
            prior['node_ids']=list(dict.fromkeys(prior['node_ids']+incoming['node_ids']))
        else:result['branches'].append(copy.deepcopy(incoming))


def report(mrg,coverage,usage,evidence,implementation):
    from .kd_s2_report import report as base_report
    text=base_report(mrg,coverage,usage,evidence,implementation).replace('KD-S-2','KD-S-3')
    branches=coverage.get('branches',[])
    if not branches:return text
    escape=lambda v:html.escape(str(v),quote=True)
    names={n['id']:n['name'] for k in ('SOP','OMN','MN') for n in mrg[k]}
    body='<section><h2>功能内的业务分支</h2><p>各分支分别适用输入、前置条件与完成条件；没有连线不代表不存在依赖。尚未取证的分支保留在缺口中。</p>'
    for b in branches:
        body+='<details open><summary>'+escape(names.get(b['sop_id'],b['sop_id']))+' / '+escape(b['name'])+'</summary><p>'+escape(b.get('trigger') if b.get('trigger_supported') else '触发条件待核实')+'</p><ul>'
        body+=''.join('<li><a href="#'+escape(n)+'">'+escape(names[n])+'</a></li>' for n in b['node_ids'] if n in names)
        body+='</ul><p>'+escape(b.get('note',''))+'</p></details>'
    return text.replace('</body>',body+'</section></body>') if '</body>' in text else text+body+'</section>'
