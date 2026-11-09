"""Requirements-led discovery and local extraction checks, without a paid judge pass."""
import copy
from collections import defaultdict
from .kd_s2_format import digest
from .kd_s3_review import claims, review_delta

OVERVIEW_RULES = '''先从sources辨认项目服务谁、解决什么问题、功能范围和交付，再用architecture定位实现。
架构线索不得缩小文档明确声明的业务范围；框架、配置或外部依赖提供的功能也保留候选，定位未知可为空。
功能是有明确业务目标、处理对象和交付的能力，可以依赖其他能力；文件、接口和函数不是功能划分单位。
同一整体业务功能的不同操作入口归入一个feature，在内部细化为业务分支；不要把一个整体功能缩小成其第一个入口。不同业务目标仍分别保留。
在features每项增加user、trigger、business_object、delivery、boundary、document_units:[文档块id]。
本轮只描述候选契约，不展开内部步骤；没有来源的字段留空。
文档覆盖清单由程序管理，不输出document_coverage，不逐段解释去向。每个功能只列实际支持它的document_units。
安装、徽章、捐赠等不作为功能，但不能因没有本仓库函数定位而排除业务能力。
区分本项目交付、集成使用的外部能力与仅推荐的其他项目。外部分发版的介绍不能直接归为本仓库功能；无法确认归属时保留边界缺口。
同一文档块可能含多个功能；代码发现的文档未述能力也可加入features。
只返回紧凑项目描述和功能清单，不复述材料、不展开步骤。每项只写区分该业务目标所需的信息。
不把潜在关联、目录顺序或共享函数当成业务依赖。'''

EXTRACTION_RULES = '''
本次目标是从可信实现还原需求，不审计算法质量、性能或运行可靠性。
feature中的用户、业务对象、触发、交付、边界是待核实的整体功能契约；局部代码不能悄悄缩小或改写它。
文档支持契约而实现只读到局部时，保留有据契约，将未读步骤写gaps；不把提交任务等同任务完成。
步骤描述业务变化，不逐函数翻译。数据转换、框架胶水、普通工具调用一般折叠；影响业务规则和交付时才展开。
输入与最终交付应与内部实际消费/产出做input_bindings/output_bindings；无依据的映射留缺口。
遇到来源矛盾或范围无法对齐时返回uncertainties:[{target:"sop"或步骤key,field,reason}]。
本包步骤先按整体目标、处理对象及交付归属：明确属于其他业务目标时，放discovered_features和gaps，不放steps。
可在步骤上给ownership:"same|other|unknown"及ownership_reason；other不能并入本功能，unknown只核对该步骤。
相同业务对象或相同文件并不代表相同业务目标；按行为的最终交付区分归属。
没有具体疑点返回空数组，不为完整性强造疑点，也不输出自我评分。覆盖relation如实选择same/subset/related/unknown。
文档中的功能范围由来源支持；代码未读完时不宣称功能不存在。发现其他目标放discovered_features并给定位。
安装部署步骤不能代替使用阶段的业务交付；文档例子或演示账号不能提升为普遍约束。声明了参数不代表实现消费了它，界面关闭或loading结束不代表保存或异步任务成功。
先后调用仅能支持顺序；成功条件、失败回退、重试和最终交付须由实际判断或行为支持。已有实现可信不等于可以省略这些语义区别。
'''


def document_units(proof, limit=1800):
    """Paragraph/section blocks with stable, visible source ranges; no semantic filtering."""
    result=[]
    for path, source in proof.items():
        rows=[];size=0
        def flush():
            if rows and any(r['text'].strip() for r in rows):
                result.append({'id':'doc.'+digest([path,rows[0]['line'],rows[-1]['line']])[:16],
                    'path':path,'start':rows[0]['line'],'end':rows[-1]['line']})
        for row in source['lines']:
            if rows and (size+len(row['text'])>limit or row['text'].startswith('#')):
                flush();rows=[];size=0
            rows.append(row);size+=len(row['text'])+1
            if not row['text'].strip() and size>=400:flush();rows=[];size=0
        flush()
    return result


def document_ledger(overview, units):
    keys={f.get('key') for f in overview.get('features',[])}
    answers={r.get('unit_id'):r for r in overview.get('document_coverage',[]) if isinstance(r,dict)}
    result=[]
    for unit in units:
        row=answers.get(unit['id'],{})
        mapped=[k for k in row.get('feature_keys',[]) if k in keys]
        mapped+= [f['key'] for f in overview.get('features',[]) if unit['id'] in f.get('document_units',[]) and f.get('key') not in mapped]
        status='mapped' if mapped else 'non_business' if row.get('status')=='non_business' and row.get('reason') else 'uncertain'
        result.append({**unit,'feature_keys':mapped,'status':status,'reason':row.get('reason') or '概览未明确说明此材料的功能去向，保留待检查'})
    return result


def unresolved_entry_groups(methods, assigned, rank):
    """Group entry clues by architectural module, never allocate one SOP per file."""
    groups=defaultdict(list)
    for m in methods:
        if m['id'] not in assigned and m.get('implementation_kind')!='distribution':groups[m['module']].append(m)
    for module, values in sorted(groups.items()):
        values.sort(key=lambda m:(rank(m),m['path'],m['start'],m['id']))
        # Small entry batches are probes, not predeclared functions. Lower-ranked
        # definitions remain in the index/coverage and can be followed on demand.
        entries=[m for m in values if rank(m)<=1] or values[:1]
        for offset in range(0,len(entries),6):yield module,entries[offset:offset+6]


def checked_extraction(calls,label,value,proof,feature,base=None,project_confirmed=False,definitions=(),repair=False):
    """Anchor/ownership checks are not semantic approval. Review concrete doubts only."""
    old={c['signature'] for c in claims(base)} if base else set()
    fresh=[c for c in claims(value) if c['signature'] not in old and not(project_confirmed and c['kind']=='MNS')]
    flagged=[];reasons=[]
    doubts=value.get('extraction_uncertainties',[])
    for c in fresh:
        reason=[]
        if not c['citations']:reason.append('字段缺少可见原文定位')
        for d in doubts:
            if d.get('target_id')==c['target_id'] and (not d.get('field') or c['field']==d['field'] or c['field'].startswith(d['field']+'/')):
                reason.append(d.get('reason','提取报告具体疑点'))
        if c['kind']=='SOP' and c['field']=='purpose' and value.get('coverage',{}).get('relation') in ('related','unknown'):
            reason.append('实际提取范围与候选业务目标尚未对齐')
        if reason:flagged.append(c['signature']);reasons.append({'target_id':c['target_id'],'field':c['field'],'reasons':reason})
    if flagged:
        result=review_delta(calls,label,value,proof,feature,base,project_confirmed,definitions,repair,
                            only_signatures=set(flagged),max_batches=1)
    else:
        result={'project_supported':True,'decisions':[{'sop_id':s['id'],'keep':True,'reason':'来源定位检查通过；未进行独立语义复核'} for s in value['mrg']['SOP']],
                'drop_facts':[],'drop_nodes':[],'drop_edges':[],'coverage':value.get('coverage',{}),'reviewed_new_facts':0}
    result['extraction_check']={'mode':'targeted' if flagged else 'programmatic','new_claims':len(fresh),
        'flagged_claims':len(flagged),'issues':reasons,'semantic_review_of_all_claims':False}
    return result


def attach_uncertainties(draft, raw):
    sid=draft['mrg']['SOP'][0]['id'];nodes=draft['mrg']['OMN']+draft['mrg']['MN']+draft['mrg']['ME']
    draft['extraction_uncertainties']=[]
    for d in raw.get('uncertainties',[]):
        if not isinstance(d,dict) or not d.get('reason'):continue
        target=d.get('target','sop')
        actual=sid if target=='sop' else next((n['id'] for n in nodes if n['id']==target or n['id'].endswith('.'+digest(target)[:10])),None)
        # Unknown local keys cannot silently discard an explicit doubt.
        draft['extraction_uncertainties'].append({'target_id':actual or sid,'field':d.get('field') if actual else 'purpose','reason':d['reason']})


def feature_sources(feature, units, proof):
    """Keep the actual declared business boundary visible during implementation reading."""
    wanted=set(feature.get('document_units',[]));result={}
    for unit in units:
        if unit['id'] not in wanted:continue
        path=unit['path'];src=proof[path]
        slot=result.setdefault(path,{**src,'lines':[]});known={l['line'] for l in slot['lines']}
        slot['lines'].extend(l for l in src['lines'] if unit['start']<=l['line']<=unit['end'] and l['line'] not in known)
    return result
