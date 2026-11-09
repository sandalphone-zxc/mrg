"""KD-S-3: requirements-led discovery, local source paths, targeted extraction checks."""
import collections,copy,json,re,time
from pathlib import Path
from .knowledge_strategies import KDiscovery
from .kd_s2_format import FORMAT,digest,definition,empty,validate,completeness
from .kd_s2_sources import Materials,atomic,longpath
from .kd_s2 import COMMON,OVERVIEW,REVIEW,RELATIONS,RELATION_REVIEW,prepare,review_apply,check_evidence,BudgetPause,prune_links
from .kd_s2_units import compile_delta,attach_project,compact_review,output_contract,split_sources,verify_saved,DETAIL_INSTRUCTION,refinement_delta
from .kd_s2_progress import merge_increment,merge_details
from .kd_s2_evidence import merge_sources
from .kd_s2_paths import project_folder,safe_path,check_maintenance
from .kd_s2_report import publish,verify
from .kd_s3_calls import Calls,ServicePause,ReservedCalls
from .kd_s3_graph import method_summary as old_method_summary,read
from .kd_s3_index import build,tool_identity,IndexMaterials
from .kd_s3_review import review_delta,apply_review,prune_with_evidence,prepare_with_evidence as prepare
from .kd_s3_support import locator_matches,normalize_raw,locate_implementations,confirmed_roots,normalize_evidence,relation_pairs
from .kd_s3_packages import entry_rank,ordered_features,behavior_packages,source_excerpt,repair_package,pair_sources
from .kd_s3_requirements import OVERVIEW_RULES,EXTRACTION_RULES,document_units,document_ledger,unresolved_entry_groups,checked_extraction,attach_uncertainties,feature_sources
from .kd_s3_contracts import obtain_overview,normalize_delta
from .kd_s3_branches import INSTRUCTION as BRANCH_INSTRUCTION,prepare_branch,carry_existing_nodes,attach_branch,merge_branches

RULE='KD-S-3/handoff-budget-11'
STEP_REVIEW=REVIEW+'\n另外返回drop_nodes:[{id,reason}]，只剔除无依据的内部MN/OMN，保留其他有效步骤和功能；检查是否将辅助函数误当独立功能、或将局部实现宣称完整交付。'
EXTRACT=COMMON+'''本次阅读的是语法与符号索引定位的实现。索引只提供实现位置线索，业务事实必须以sources原文为依据。
一个SOP代表一项业务功能；OMN是该SOP内部操作步骤，MN是其内部业务状态/结果/检查点步骤。函数不等于业务步骤。
一次仅描述本工作包实际支持的一条业务路径及其功能契约。已确认内容在previous_capability，保留目标与端口key，仅补新事实；不重写旧步骤。
返回简洁JSON：{sop:{name,purpose,inputs:[],outputs:[],preconditions:[],rules:[],completion_conditions:[],exceptions:[{condition,response}]},
steps:[{key,name,purpose,actor:"human|system|external|unknown",inputs:[],outputs:[],rules:[]}],
states:[{key,name,purpose,state_description,inputs:[],outputs:[],rules:[]}],
links:[{key,source:步骤key,target:步骤key,relation:"delivery|conditional_next|feedback|retry|invalidation",condition,meaning,transfers:[{output_key,input_key,meaning}]}],
input_bindings:[{input_key,step:步骤key,node_input_key,meaning}],output_bindings:[{output_key,step:步骤key,node_output_key,meaning}],
evidence:[{target:"sop"或步骤/状态/关系key,field:"purpose"或"rules/0"等具体字段路径,path,line}],
implementations:[{target:"sop"或步骤key,path,line,symbol}],
coverage:{relation:"same|subset|related|unknown",covered:[],remaining:[],reason,locators:[]},
discovered_features:[{key,name,goal,locators:[]}],gaps:[],pending_relations:[]}。
输入输出为{key,name,meaning,necessity:"required|optional|unknown"}。不输出完整MRG，不重复原文quote；程序按行自动保存来源。
purpose、输入输出、规则、异常、完成条件、步骤purpose和关系meaning必须给相应字段证据。所有key局部唯一。
校验、分支、存储、异常、最终交付按业务动作归纳，不机械逐函数拆分；普通中间变量不生成MN。
允许仅保存当前有据的契约或部分步骤，剩余路径写gaps。不能把局部辅助能力当作完成整个候选。
确属技术辅助而不构成业务功能时返回sop:null,classification:"technical",gaps:[理由]；不因缺少代码定位或前置依赖拒绝功能。
旧功能缺失、未知、未读取均不得补造。调用不是功能依赖；功能间关系只给pending_relations线索。'''
EXTRACT+='''\nfeature与related_entries提供功能分组线索；behavior_entry和sources是本包实际读到的实现。功能边界依据业务对象、目标与交付，而非当前首个函数。
本包可以覆盖同一功能的多个操作；不要把查询、创建等并列操作强行说成彼此的内部步骤。没有顺序证据不连线。
文档支持的完整功能范围可作为契约，未读实现必须在gaps说明；只有局部依据时如实保留局部范围。抽象方法只能说明意图，不能作为已实现步骤。
优先给出简短且完整的结果；同一业务事实只描述一次。缺乏交接证据时省略links和states，而不是分析所有可能的流程。
工程配置不构成独立功能；但用户可使用的组件、开发者集成功能不能仅因包含技术术语就被拒绝。
confirmed_capabilities仅是已确认功能上下文：本包若只是重复已保存行为且没有新业务信息，返回sop:null并说明重复对象，不再造一个SOP。相同文件不等于相同功能。
同一功能可包含不同入口；分支专属输入输出在meaning说明适用分支，necessity不能把只在某入口产生的结果标成全功能每次必需。完成条件分别说明适用路径，不把互斥结果当成同时必须满足。
绑定需要给字段来源；若步骤消费/产生的对象与功能端口一致，应保留有据的input_bindings和output_bindings。
不要复述函数签名、逐个分析无关入口或展开全部可能路径。先确定本包一条主路径，简写结果。已知事实直接给结果；不确定内容只写具体gap，停止反复推敲。内部节点只给实际消费与产出的对象，不复制SOP全部配置参数和规则。'''
EXTRACT+=EXTRACTION_RULES
EXTRACT+=BRANCH_INSTRUCTION
DETAIL=EXTRACT+'\nconfirmed_contract和confirmed_steps是已确认结果；known_branches列出已有业务分支。仅输出新增步骤和事实，不重述旧步骤。以branch表达当前路径，整体name/purpose保持不变，不使用scope_extension。contract_additions仅放有据的全功能共同事实，当前路径事实放branch。不要重复返回完整sop；其他整体业务目标放discovered_features。'
REPAIR='\n上次结果无法作为完整结构使用。本次只输出本行为的最小有据结果；省略可选数组和其他分支。首次契约只给名称、目标和直接输入输出；内部细节留待后续包。不要重复展开整个功能。'

def fingerprint():
    files={p.name:digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}
    return digest([RULE,'standalone-package-v1',files])

def folder_for(workspace,repo,commit,jid):
    if not re.fullmatch('[a-fA-F0-9]{40}',commit) or not re.fullmatch(r'[\w-]+',jid):raise ValueError('无效任务身份')
    return safe_path(Path(workspace)/'mrg-project/knowledge',project_folder(workspace,repo,True)/'KD-S-3'/commit/jid)

def sources_for(materials,methods):
    proof={}
    for m in methods:
        f=materials.read(m['path'])
        if not f:continue
        start=max(1,int(m.get('start') or 1));end=min(len(f['lines']),max(start,int(m.get('end') or start)))
        slot=proof.setdefault(m['path'],{k:f[k] for k in ('sha256','kind','representation')});lines=slot.setdefault('lines',[])
        known={v['line'] for v in lines}
        for i in range(start,end+1):
            if i not in known:lines.append({'line':i,'text':f['lines'][i-1]})
        lines.sort(key=lambda v:v['line'])
    return proof

def method_summary(n):
    return {**old_method_summary(n),'implementation_kind':n.get('implementation_kind','unknown'),'behavior_start':n.get('behavior_start')}

def incremental(raw,base):
    raw=normalize_delta(raw)
    value=refinement_delta(raw,base)
    extension=raw.get('scope_extension')
    if extension:
        evidence=[e for e in raw.get('evidence',[]) if e.get('target')=='sop' and e.get('field')=='purpose']
        if not isinstance(extension,dict) or not all(extension.get(k) for k in ('purpose','name','reason')) or not evidence or extension.get('previous_goal')!=base['mrg']['SOP'][0]['purpose']:
            value.setdefault('gaps',[]).append('范围改变未获采用，保留已有功能目标与新增步骤；缺少原目标、改变理由或新来源：'+str(extension))
        else:
            value['sop'].update({k:extension[k] for k in ('name','purpose')})
            value['evidence']=[e for e in value['evidence'] if not(e.get('target')=='sop' and e.get('field')=='purpose')]+evidence
            value.setdefault('uncertainties',[]).append({'target':'sop','field':'purpose','reason':'范围改变须核对是否保留已有业务目标：'+extension['previous_goal']+'；改变理由：'+extension['reason']})
            value['boundary_change']=extension
    return value

def merge_reviewed(base,extra):
    result=merge_details(merge_increment(base,extra),extra)
    merge_branches(result,extra)
    old=result['mrg']['SOP'][0];new=extra['mrg']['SOP'][0]
    if old['purpose']!=new['purpose'] and extra.get('boundary_change'):
        old.update(name=new['name'],purpose=new['purpose'])
        result['evidence']=[e for e in result['evidence'] if not(e['target_id']==old['id'] and e['field']=='purpose')]
        result['evidence'] += [copy.deepcopy(e) for e in extra['evidence'] if e['target_id']==old['id'] and e['field']=='purpose']
        old['source_refs']=[e['id'] for e in result['evidence'] if e['target_id']==old['id']]
        result.setdefault('boundary_changes',[]).append(copy.deepcopy(extra['boundary_change']))
    return result

def schedule(overview,graph,repo):
    methods=[method_summary(n) for n in graph['methods']];byid={m['id']:m for m in methods};features=[];assigned=set()
    for raw in overview.get('features',[]):
        hints=raw.get('locators',[])
        roots=[m['id'] for m in methods if any(locator_matches(h,m) for h in hints)]
        key=raw.get('key') or digest(raw)[:16];f={**raw,'id':'SOP.'+digest([repo,key])[:18],'roots':sorted(set(roots)),'module':byid[roots[0]]['module'] if roots else 'document','document_candidate':True}
        f['locators']=[(h.get('path','')+('::'+h['symbol'] if h.get('symbol') else '')) if isinstance(h,dict) else h for h in hints]
        features.append(f);assigned.update(roots)
    for module,entries in unresolved_entry_groups(methods,assigned,entry_rank):
        roots=[m['id'] for m in entries];paths=sorted({m['path'] for m in entries})
        key='entry.'+digest([module,roots])[:16]
        features.append({'key':key,'id':'SOP.'+digest([repo,key])[:18],'name':'待辨认业务目标：'+module,
            'goal':'结合项目需求辨认入口服务的业务目标和交付；可属于已有功能，禁止按文件或辅助函数建立功能。',
            'locators':paths,'roots':roots,'module':module,'document_candidate':False,'discovery_probe':True})
    return ordered_features(features,byid),byid

def assemble(overview,accepted,schema):
    result={'mrg':empty(overview),'evidence':[],'implementations':[]}
    for value in accepted:
        m=result['mrg']
        if not m['MNS']['source_refs'] and value['mrg']['MNS']['source_refs']:m['MNS']=copy.deepcopy(value['mrg']['MNS'])
        for k in ('SOP','OMN','MN','ME','business_objects','Sessions','SE','open_items'):
            for v in value['mrg'][k]:
                if v not in m[k]:m[k].append(copy.deepcopy(v))
        for k in ('evidence','implementations'):
            for v in value[k]:
                if v['target_id']==m['MNS']['id'] and v.get('id') not in m['MNS']['source_refs']:continue
                if v not in result[k]:result[k].append(copy.deepcopy(v))
    result['mrg']['MNS']['SOP_refs']=[s['id'] for s in result['mrg']['SOP'] if s['parent_sop_id'] is None]
    validate(result['mrg'],schema);return result

@KDiscovery.register
class GraphDiscovery(KDiscovery):
    source='github';strategy='KD-S-3';output_format=FORMAT
    description='文档与轻量代码索引驱动的功能、内部步骤和业务交接挖掘'
    def __init__(self,provider,workspace,api=None):self.provider,self.workspace,self.api=provider,Path(workspace),api

    def extract(self,meta,files,request,job_id,progress=None):
        check_maintenance(self.workspace);note=progress or (lambda _:None)
        repo,commit=meta['repo'],meta['commit'];folder=longpath(folder_for(self.workspace,repo,commit,job_id));folder.mkdir(parents=True,exist_ok=True)
        raw=request.get('format_bytes') or (self.workspace/'mrg.format.json').read_bytes();schema=json.loads(raw)
        if schema['properties']['format']['const']!=FORMAT:raise ValueError('不兼容MRG格式')
        frozen=folder/'format-definition.json'
        if frozen.exists() and frozen.read_bytes()!=raw:raise ValueError('格式断点不匹配')
        frozen.write_bytes(raw)
        identity={'repo':repo,'commit':commit,'strategy':self.strategy,'rule':RULE,'rule_hash':fingerprint(),'format':FORMAT,'schema_hash':digest(raw),
            'model':request.get('model','offline'),'model_url':request.get('model_url',''),'model_config_hash':request.get('model_config_hash'), 'run_id':job_id}
        materials=IndexMaterials(self.workspace,folder,repo,commit,self.api,files)
        try:
            note('固定源码并建立语法、符号与直接引用索引');graph,gm=build(materials,self.workspace,note)
        except Exception as exc:
            atomic(folder/'graph-failure.json',{'identity':identity,'stage':'graph','reason':str(exc),'model_requests':0});raise
        identity['tool_hash']=digest(gm['identity']['tool']);identity['tool']=gm['identity']['tool']
        parser_diagnostics=[]
        for log in sorted((folder/'code-graph-light').glob('*/*.log')):
            lines=log.read_text(encoding='utf8',errors='replace').splitlines()
            for i,line in enumerate(lines):
                if re.search(r'\b(WARN|ERROR|Exception)\b',line):
                    parser_diagnostics.append({'log':str(log.relative_to(folder)),'line':i+1,
                        'status':'parser_warning' if 'WARN' in line else 'parser_error',
                        'reason':'\n'.join(lines[i:min(i+2,len(lines))])})
        calls=Calls(self.provider,folder,identity)
        state_path=folder/'work-state.json'
        state=read(state_path) if state_path.exists() else {'identity':identity,'accepted':{},'features':[],'ledger':{},'failures':[],'removed':[],'relation_checks':[],'repair_used':False}
        if state['identity']!=identity:raise ValueError('任务模型、代码图或规则改变，不能串用断点')
        overview={'MNS':{'id':'MNS.'+digest(repo)[:12],'name':repo,'goal':'项目整体目标待复核','users':[],'scenarios':[],'scope':[],'outcomes':[],'success_criteria':[],'SOP_refs':[],'source_refs':[]}}
        status='partial';phase='overview';doc={}
        try:
            docs=[e['path'] for e in materials.tree if e.get('kind') in ('document','example') and ('readme' in e['path'].lower() or e['path'].lower().startswith(('docs/','doc/')))]
            docs.sort(key=lambda p:(p.count('/'),p.lower()));remaining=14000
            for path in docs:
                f=materials.read(path)
                if not f:continue
                lines=[]
                for i,line in enumerate(f['lines'],1):
                    if len(line)+1>remaining:break
                    lines.append({'line':i,'text':line});remaining-=len(line)+1
                if lines:doc[path]={**{k:f[k] for k in ('sha256','kind','representation')},'lines':lines}
                if remaining<200:break
            methods=[method_summary(n) for n in graph['methods']];modules=collections.defaultdict(list)
            for m in methods:modules[m['module']].append(m)
            for values in modules.values():values.sort(key=lambda m:(entry_rank(m),m['path'],m['start']))
            index=[];used=0
            for tier in range(4):
                tier_modules={k:[m for m in v if entry_rank(m)==tier] for k,v in modules.items()}
                for i in range(max((len(v) for v in tier_modules.values()),default=0)):
                    for module in sorted(tier_modules):
                        if i>=len(tier_modules[module]):continue
                        m=tier_modules[module][i];size=len(json.dumps(m,ensure_ascii=False))
                        if used+size<=6000:index.append(m);used+=size
            note('理解项目目标并对齐功能与代码入口')
            units=document_units(doc)
            overview=obtain_overview(calls,OVERVIEW+OVERVIEW_RULES+'\narchitecture来自语法定义索引，不是已确认业务功能。按业务目标、对象、交付分组，不按单函数分功能；用真实path或symbol定位，保留文档支持的功能边界。material_modules仅是原文目录线索，声明式资源也可能承载功能；不能仅因没有函数而忽略。',
                {'repo':repo,'project_id':overview['MNS']['id'],'sources':doc,'document_units':units,'architecture':index,'modules':list(modules),'index_omitted':len(methods)-len(index),
                 'material_modules':dict(collections.Counter('/'.join(e['path'].split('/')[:2]) for e in materials.tree))},state,state_path)
            state['document_coverage']=document_ledger(overview,units)
            overview=normalize_evidence(overview,doc,'project_evidence')
            state.setdefault('locator_diagnostics',[]).extend(overview['locator_diagnostics'])
            overview['MNS']={'id':'MNS.'+digest(repo)[:12],'name':repo,'goal':'项目整体目标待复核','users':[],'scenarios':[],'scope':[],'outcomes':[],'success_criteria':[],'SOP_refs':[],'source_refs':[]}
            features,byid=schedule(overview,graph,repo)
            if not state['features']:
                # Unaccounted document blocks remain actual work, not invisible losses.
                for row in state['document_coverage']:
                    if row['status']!='uncertain':continue
                    key=row['id'];features.append({'key':key,'id':'SOP.'+digest([repo,key])[:18],
                        'name':'待核实文档业务范围','goal':'识别本材料中的业务功能；已知功能补充定位，技术说明不输出SOP。',
                        'locators':[row['path']],'roots':[],'module':'document','document_candidate':True,
                        'document_probe':row})
                state['features']=features;atomic(state_path,state)
            doc_context=source_excerpt(doc,[(e.get('path'),e.get('line',1)) for e in overview.get('project_evidence',[])],1800)
            if not doc_context:
                short=split_sources(doc,1800);doc_context=short[0] if short else {}
            features=state['features'];queue=list(features);phase='features'
            while queue:
                f=queue.pop(0);sid=f['id'];entry=state['ledger'].setdefault(sid,{'id':sid,'name':f['name'],'roots':f['roots'],'pages_read':0,'status':'pending'})
                if entry['status'] in ('failed','technical','reviewed','unverified_technical'):continue
                plan_path=folder/'work-packages'/(sid+'.json')
                if plan_path.exists():packages=read(plan_path)['packages']
                else:
                    packages=behavior_packages(f,graph,byid,lambda ms:sources_for(materials,ms))
                    if f.get('document_probe'):
                        u=f['document_probe'];src=doc.get(u['path'])
                        selected={u['path']:{**src,'lines':[l for l in src['lines'] if u['start']<=l['line']<=u['end']]}} if src else {}
                        packages=[{'sources':selected,'entry':{'kind':'document_probe'},'continuation':0,'definition_pages':1,'graph':{'nodes':[],'edges':[]}}] if selected else []
                    if not packages:
                        # A document/declarative capability need not have a method.
                        from .kd_s2_evidence import plan
                        plan_value=plan(materials,f,8000)
                        packages=[{'sources':p['proof'],'entry':{'kind':'material','paths':plan_value['paths']},'continuation':i,'definition_pages':len(plan_value['pages']),
                            'graph':{'nodes':[],'edges':[],'limits':['未定位可解析实现，按可见文档或声明核实功能，不推测内部操作。']}} for i,p in enumerate(plan_value['pages'])]
                    atomic(plan_path,{'feature':f,'packages':packages})
                entry['pages_total']=len(packages)
                if entry['pages_read']>=len(packages):entry['status']='reviewed' if sid in state['accepted'] else 'unverified_technical';continue
                # Only reserve an executable relation pair; repair shares this round's budget.
                reserve=2 if relation_pairs(state,graph,byid.values()) else 0
                if calls.remaining()<1+reserve:status='paused_budget';break
                page=entry['pages_read'];package=packages[page]
                context=merge_sources(doc_context,feature_sources(f,units,doc))
                proof=merge_sources(package['sources'],context);base=state['accepted'].get(sid);label=f'{sid}-page-{page}'
                entry['unexpanded_references']=sorted(set(entry.get('unexpanded_references',[]))|set(package.get('frontier',[])))
                draft=None;prior_request=None
                for attempt in range(2):
                    if attempt:
                        if page in entry.get('repaired_pages',[]) or calls.remaining()<1+reserve:break
                        entry.setdefault('repaired_pages',[]).append(page);atomic(state_path,state)
                        if draft is None:
                            pieces=repair_package(package)
                            if len(pieces)>1:
                                packages[page:page+1]=pieces;atomic(plan_path,{'feature':f,'packages':packages});entry['pages_total']=len(packages)
                            package=packages[page];proof=merge_sources(package['sources'],context)
                    try:
                        note('读取处理链并生成功能步骤：'+f['name'])
                        if draft is None:
                            payload={'feature':{k:f[k] for k in ('id','name','goal','user','trigger','business_object','delivery','boundary','discovery_probe') if k in f},'behavior_entry':package['entry'],
                                'overview':overview['project'],'graph':package['graph'],'sources':proof,'output_contract':output_contract(schema,True),
                                'remaining_definition_pages':package['definition_pages']-package['continuation']-1,
                                'unexpanded_references':[byid[r] for r in package.get('frontier',[]) if r in byid],
                                'related_entries':[byid[r] for r in f['roots'][:40] if r in byid],
                                'confirmed_capabilities':[{'id':k,'name':v['value']['mrg']['SOP'][0]['name'],'purpose':v['value']['mrg']['SOP'][0]['purpose']} for k,v in state['accepted'].items() if k!=sid]}
                            prompt=DETAIL if base else EXTRACT
                            if base:
                                payload.update(confirmed_contract={k:v for k,v in base['value']['mrg']['SOP'][0].items() if k not in ('source_refs','input_bindings','output_bindings')},
                                    confirmed_steps=[{k:n[k] for k in ('id','name','purpose')} for kind in ('OMN','MN') for n in base['value']['mrg'][kind]])
                                payload['known_branches']=base['value'].get('branches',[])
                            if attempt:prompt+=REPAIR;payload['repair_scope']='minimal_behavior_only'
                            signature=digest([prompt,payload])
                            if signature==prior_request:raise ValueError('修复工作包没有变化；拒绝重复调用')
                            prior_request=signature
                            raw=normalize_delta(calls.call(label+f'-{attempt}-extract',prompt,payload))
                            if not base and raw.get('sop') is None:
                                entry.update(status='technical_candidate',reason=raw.get('gaps',[]));break
                            compile_proof=merge_sources(base['proof'],proof) if base else proof
                            raw=prepare_branch(raw,base['value'] if base else None)
                            if raw.pop('scope_extension',None):raw.setdefault('gaps',[]).append('整体目标变更未采用；本轮只补充有据业务分支。')
                            if base:raw=incremental(raw,base['value'])
                            raw=normalize_evidence(normalize_raw(raw),compile_proof)
                            state.setdefault('locator_diagnostics',[]).extend(raw['locator_diagnostics'])
                            draft=compile_delta(raw,f,overview,compile_proof,tolerant_evidence=True);attach_project(draft,overview,proof)
                            if base:carry_existing_nodes(draft,base['value'])
                            if raw.get('boundary_change'):draft['boundary_change']=raw['boundary_change']
                            attach_uncertainties(draft,raw)
                            if state.get('project_confirmed'):
                                draft['mrg']['MNS']=copy.deepcopy(state['project_confirmed']['MNS'])
                                draft['mrg']['MNS']['SOP_refs']=[sid]
                                draft['evidence']=[e for e in draft['evidence'] if e['target_id']!=draft['mrg']['MNS']['id']]+copy.deepcopy(state['project_confirmed']['evidence'])
                            # Source review repairs visible anchors before strict cleanup.
                            # A missing citation is not yet an unsupported business fact.
                        note('检查提取对应与覆盖：'+f['name'])
                        reviewproof=proof
                        if base:reviewproof=merge_sources(proof,source_excerpt(base['proof'],[(e['path'],e['line']) for e in draft['evidence']],6000))
                        review_feature={**f,'confirmed_capabilities':[{'id':k,'name':v['value']['mrg']['SOP'][0]['name'],'purpose':v['value']['mrg']['SOP'][0]['purpose']} for k,v in state['accepted'].items() if k!=sid]}
                        review=checked_extraction(ReservedCalls(calls,reserve),label+f'-{attempt}',draft,reviewproof,review_feature,base['value'] if base else None,bool(state.get('project_confirmed')),list(byid.values()),bool(attempt))
                        state.setdefault('extraction_checks',[]).append({'feature_id':sid,'page':page,**review['extraction_check']})
                        candidate=copy.deepcopy(draft);rejected,removed=apply_review(candidate,review);state['removed']+=removed
                        if rejected:raise ValueError('核心功能未通过复核：'+str(review['decisions']))
                        drop={n['id'] for n in review.get('drop_nodes',[])}
                        for kind in ('OMN','MN'):candidate['mrg'][kind]=[n for n in candidate['mrg'][kind] if n['id'] not in drop]
                        prune_with_evidence(candidate)
                        ids={n['id'] for k in ('SOP','OMN','MN','ME') for n in candidate['mrg'][k]}|{candidate['mrg']['MNS']['id']}
                        candidate['evidence']=[e for e in candidate['evidence'] if e['target_id'] in ids]
                        candidate['implementations']=[e for e in candidate['implementations'] if e['target_id'] in ids]
                        state['removed']+=review.get('drop_nodes',[])
                        candidate_proof=merge_sources(base['proof'],proof) if base else proof
                        locate_implementations(candidate,candidate_proof,list(byid.values()))
                        candidate,invalid,removed=prepare(candidate,candidate_proof,schema,[f]);state['removed']+=removed
                        if invalid or not candidate['mrg']['SOP']:raise ValueError('复核后核心字段或结构无效：'+str(invalid))
                        validate(candidate['mrg'],schema);check_evidence(candidate,candidate_proof,schema)
                        candidate['coverage']=review.get('coverage',{})
                        candidate['extraction_check']=review['extraction_check']
                        attach_branch(candidate,raw)
                        if base:
                            if draft.get('boundary_change'):candidate['boundary_change']=draft['boundary_change']
                            candidate=merge_reviewed(base['value'],candidate);proof=merge_sources(base['proof'],proof)
                            validate(candidate['mrg'],schema);check_evidence(candidate,proof,schema)
                        state['accepted'][sid]={'value':candidate,'proof':proof};entry['pages_read']+=1
                        if candidate.get('discovered_features'):
                            found,_=schedule({'features':candidate['discovered_features']},graph,repo)
                            for new in found:
                                if new.get('document_candidate') and new['id'] not in {v['id'] for v in state['features']}:
                                    new['discovery_parent']=sid;state['features'].append(new);queue.append(new)
                        if candidate['mrg']['MNS']['source_refs']:
                            state['project_confirmed']={'MNS':copy.deepcopy(candidate['mrg']['MNS']),'evidence':[copy.deepcopy(e) for e in candidate['evidence'] if e['target_id']==candidate['mrg']['MNS']['id']]}
                        entry['scope_claim']=candidate.get('coverage',{});entry['status']='reviewed' if entry['pages_read']==len(packages) else 'partial'
                        entry['confirmed_contract']={k:candidate['mrg']['SOP'][0][k] for k in ('name','purpose')}
                        entry['candidate_goal']=f.get('goal');entry['scope_complete']=False
                        entry['branch_count']=len(candidate.get('branches',[]))
                        break
                    except (BudgetPause,ServicePause):raise
                    except Exception as exc:
                        local=isinstance(exc,(ValueError,KeyError,TypeError,IndexError,StopIteration)) or getattr(exc,'diagnostic',{}).get('code') in ('truncated','invalid_json','empty_content')
                        if not local:raise
                        state['failures'].append({'id':sid,'page':page,'attempt':attempt,'phase':'review' if draft else 'extract','reason':str(exc)[:1200],'type':type(exc).__name__})
                        entry['status']='failed'
                if entry['status']=='technical_candidate':
                    entry.setdefault('skipped_pages',[]).append({'page':page,'reason':entry.get('reason',[])})
                    entry['pages_read']+=1
                    entry['status']='needs_next_behavior' if entry['pages_read']<len(packages) else 'unverified_technical'
                if entry['status']=='failed':
                    entry.setdefault('failed_pages',[]).append(page);entry['pages_read']+=1
                    entry['status']='needs_next_behavior' if entry['pages_read']<len(packages) else 'partial_failed'
                if entry['status'] in ('partial','needs_next_behavior'):
                    # Alternate breadth and continuation; a technical page cannot end a candidate.
                    # One continuation gets a turn after one fresh candidate. Never
                    # let either breadth-only or a single long handler own the round.
                    if not state.get('last_was_continuation') and sid in state['accepted']:
                        queue.insert(min(1,len(queue)),f);state['last_was_continuation']=True
                    else:queue.append(f);state['last_was_continuation']=False
                atomic(state_path,state)
            phase='relations';result=assemble(overview,[x['value'] for x in state['accepted'].values()],schema)
            prior=state.get('assembled')
            if prior:
                edges=[e for e in prior['mrg']['ME'] if e['level']=='function']
                result['mrg']['ME'].extend(e for e in edges if e not in result['mrg']['ME'])
                edge_ids={e['id'] for e in edges}
                result['evidence'].extend(e for e in prior['evidence'] if e['target_id'] in edge_ids and e not in result['evidence'])
                prune_links(result['mrg']);validate(result['mrg'],schema)
            allproof=doc
            for value in state['accepted'].values():allproof=merge_sources(allproof,value['proof'])
            state['assembled']=result
            self.relations(result,state,graph,allproof,calls,schema,note,state_path)
        except BudgetPause as exc:status='paused_budget';state['failures'].append({'phase':phase,'reason':str(exc)})
        except Exception as exc:
            status='paused_service' if isinstance(exc,ServicePause) or hasattr(exc,'kind') else 'failed'
            state['failures'].append({'phase':phase,'reason':str(exc)[:1200],'type':type(exc).__name__})
        atomic(state_path,state)
        result=state.get('assembled') or assemble(overview,[x['value'] for x in state['accepted'].values()],schema)
        m=result['mrg'];m['open_items']+=completeness(m)
        entries=list(state['ledger'].values());processed={r for e in entries if e['status']=='reviewed' and not e.get('failed_pages') for r in e['roots']}
        remaining=[method_summary(n) for n in graph['methods'] if n['id'] not in processed]
        if remaining or graph['omissions']:m['open_items'].append({'target_id':m['MNS']['id'],'topic':'coverage','status':'not_read','description':'存在未完成入口或代码图解析缺口，详见coverage.json','locators':[]})
        coverage={'status':status,'strategy':self.strategy,'failures':state['failures'],'removed':state['removed'],'feature_ledger':entries,'remaining':remaining,
            'branches':[b for a in state['accepted'].values() for b in a['value'].get('branches',[])],
            'locator_diagnostics':state.get('locator_diagnostics',[]),'document_coverage':state.get('document_coverage',[]),
            'extraction_checks':state.get('extraction_checks',[]),'semantic_review_policy':'targeted_doubts_only',
            'graph':{'nodes':gm['nodes'],'edges':gm['edges'],'methods':gm['methods'],'limits':graph['limits'],'omissions':graph['omissions'],'parser_diagnostics':parser_diagnostics},
            'relations':state['relation_checks'],'timing':{'source_seconds':gm['acquisition_seconds'],'graph_seconds':gm['graph_seconds']},
            'execution':{'round_state':'service_paused' if status=='paused_service' else 'finished','packages_reviewed':sum(e['pages_read'] for e in entries),
                'packages_failed':sum(len(e.get('failed_pages',[])) for e in entries),'packages_pending':len(remaining),'global_completeness':'not_claimed'}}
        validate(m,schema)
        # Shared publisher/renderer is deterministic; replace only strategy labels.
        saved=publish(folder,identity,m,result['evidence'],result['implementations'],coverage,calls.state,materials.files)
        manifest=read(folder/'manifest.json');manifest['strategy']=self.strategy
        from .kd_s3_branches import report as branch_report
        text=branch_report(m,coverage,read(folder/'usage.json'),read(folder/'evidence.json'),read(folder/'implementation-map.json'));(folder/'report.html').write_text(text,encoding='utf8')
        manifest['files']['report.html']=digest((folder/'report.html').read_bytes())
        atomic(folder/'code-graph-manifest.json',gm);manifest['files']['code-graph-manifest.json']=digest((folder/'code-graph-manifest.json').read_bytes())
        atomic(folder/'manifest.json',manifest);verify(folder);saved['manifest']=manifest
        return saved

    def relations(self,result,state,graph,proof,calls,schema,note,state_path):
        from .kd_s2_enrichment import namespace_relations
        from .kd_s2_supplement import Supplement
        sops=result['mrg']['SOP']
        byid={n['id']:method_summary(n) for n in graph.get('methods',[])}
        for pair in relation_pairs(state,graph,byid.values()):
            if calls.remaining()<1:state['relation_checks'].append({'ids':list(pair),'status':'budget_pending'});continue
            group=[{k:v for k,v in s.items() if k not in ('source_refs','input_bindings','output_bindings')} for s in sops if s['id'] in pair]
            pairproof=pair_sources(pair,state,graph,byid)
            total_lines=sum(len(s['lines']) for sid in pair for s in state['accepted'][sid]['proof'].values())
            selected_lines=sum(len(s['lines']) for s in pairproof.values())
            key=digest(pair)[:16];note('核对功能间业务交接：'+'、'.join(s['name'] for s in group))
            for attempt in range(2):
                if calls.remaining()<1:
                    state['relation_checks'].append({'ids':list(pair),'status':'budget_pending'});break
                try:
                    relationproof=pairproof
                    if attempt:
                        parts=split_sources(pairproof,max(1,sum(len(l['text'])+1 for s in pairproof.values() for l in s['lines'])//2))
                        relationproof=parts[0] if parts else {}
                    proposal=calls.call('relations-'+key+f'-{attempt}',RELATIONS+(REPAIR if attempt else ''),
                        {'functions':group,'schema':{'ME':schema['$defs']['ME']},'sources':relationproof,'scope':'只核实本次交接切片；未见实现仍为未知'})
                    proposal=namespace_relations(proposal,key)
                    # Extract once; apply_relations enforces evidence and layer references.
                    # A structurally invalid subset is removed/recorded, not a new full review.
                    review={'drop_edges':[]}
                    if not isinstance(review.get('drop_edges'),list):raise ValueError('关系复核缺少逐项结果')
                    checked,removed=Supplement.apply_relations(copy.deepcopy(result),proposal,review,set(pair),relationproof,schema)
                    result=checked;state['removed']+=removed
                    state['relation_checks'].append({'ids':list(pair),'status':'reviewed','scope':'selected_handoff_sources_only',
                        'unread_source_lines':max(0,total_lines-selected_lines),'unresolved':proposal.get('unresolved',[])})
                    break
                except (BudgetPause,ServicePause):raise
                except Exception as exc:
                    local=isinstance(exc,(ValueError,KeyError,TypeError,IndexError)) or getattr(exc,'diagnostic',{}).get('code') in ('truncated','invalid_json','empty_content','output_budget')
                    if not local:raise
                    state['failures'].append({'phase':'relations','ids':list(pair),'attempt':attempt,'reason':str(exc)[:1200]})
                    if attempt or calls.remaining()<1:state['relation_checks'].append({'ids':list(pair),'status':'failed','reason':str(exc)[:1200]});break
            state['assembled']=result;atomic(state_path,state)
        state['assembled']=result
