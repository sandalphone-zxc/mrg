"""Versioned syntax/definition index. It is a locator, not a runtime call graph."""
import ast,collections,hashlib,importlib,importlib.metadata,io,json,re,sys,time,zipfile,subprocess
from pathlib import Path,PurePosixPath
from .kd_s2_format import digest
from .kd_s2_sources import Materials,atomic
from .kd_s2_architecture import module_key,resolve
from .kd_s3_graph import vue_script

LANG={'.py':'python','.js':'javascript','.jsx':'javascript','.mjs':'javascript','.cjs':'javascript',
      '.ts':'typescript','.tsx':'tsx','.vue':'typescript','.php':'php','.java':'java','.sh':'bash','.bash':'bash',
      '.cpp':'cpp','.cc':'cpp','.c':'cpp','.h':'cpp','.hpp':'cpp','.scala':'scala'}
DEFINITIONS={'function_definition','function_declaration','method_definition','method_declaration','constructor_declaration','arrow_function','function_expression'}
CALLS={'call','call_expression','method_invocation','function_call_expression','member_call_expression','command'}
EXCLUDED={'node_modules','vendor','.git','dist','build','__pycache__','.venv','venv'}

def tool_identity(workspace):
    from .runtime import identity
    return identity()

def parser_for(workspace,language):
    from tree_sitter import Language,Parser
    module=importlib.import_module('tree_sitter_'+('typescript' if language=='tsx' else language))
    name={'typescript':'language_typescript','tsx':'language_tsx','php':'language_php'}.get(language,'language')
    return Parser(Language(getattr(module,name)()))

def language_for(path,text=''):
    language=LANG.get(PurePosixPath(path).suffix.lower())
    if not language and text.startswith('#!') and re.search(r'\b(bash|sh)\b',text.splitlines()[0]):language='bash'
    return language

class IndexMaterials(Materials):
    def inventory(self):
        tree=super().inventory();known={x['path'] for x in tree}
        raw=json.loads((self.folder/'inventory.json').read_text(encoding='utf8'))
        for e in raw.get('tree',[]):
            # Extensionless docs are handled by Materials; only executable files
            # warrant the additional shebang probe. Dotfiles are not code entries.
            if e.get('type')=='blob' and e['path'] not in known and (PurePosixPath(e['path']).suffix in LANG or (not PurePosixPath(e['path']).suffix and e.get('mode')=='100755')) and not EXCLUDED.intersection(PurePosixPath(e['path']).parts):
                if e.get('size',0)<=8_000_000:self.tree.append({**e,'kind':'implementation'})
        return self.tree

def generated_reason(path,text):
    header=text[:4000]
    if re.search(r'(?i)(?:@generated|generated file|auto[- ]generated|do not edit)',header):return '生成标记'
    if re.search(r'(?i)\.(min|bundle)\.[cm]?js$',path):return '压缩或打包文件名'
    if len(text)>100000 and ('define.amd' in header and 'exports' in header and 'factory' in header):return '大型UMD分发包'
    if len(text)>100000 and ('webpackBootstrap' in header or '__webpack_modules__' in header):return '大型Webpack分发包'
    return None

def fetch_archive(repo,commit):
    import httpx
    if not re.fullmatch(r'[\w.-]+/[\w.-]+',repo) or not re.fullmatch(r'[0-9a-fA-F]{40}',commit):raise ValueError('无效固定仓库版本')
    chunks=[];size=0;deadline=time.monotonic()+90
    with httpx.Client(timeout=20,trust_env=False,follow_redirects=False) as client:
        with client.stream('GET',f'https://codeload.github.com/{repo}/zip/{commit}') as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                if time.monotonic()>deadline:raise ValueError('源码归档下载总时限90秒')
                size+=len(chunk)
                if size>128_000_000:raise ValueError('源码归档超过128MB采集边界')
                chunks.append(chunk)
    return b''.join(chunks)

def hydrate_archive(materials,note):
    """Read ZIP members as bytes only; verify against fixed Git blob IDs. Never extract paths."""
    missing=[e for e in materials.tree if e.get('kind') in ('implementation','interface','document','example') and not (materials.folder/'file-index'/(digest(e['path'])+'.json')).exists()]
    if not missing:return
    inventory=json.loads((materials.folder/'inventory.json').read_text(encoding='utf8'))
    if sum(e.get('size',0) for e in inventory.get('tree',[]))>32_000_000:
        note('仓库包含较多非源码材料，按需获取缺失源码，不下载整库归档');return
    note('补齐固定 commit 原文缓存')
    try:
        raw=fetch_archive(materials.repo,materials.commit)
        if len(raw)>128_000_000:raise ValueError('源码归档超过128MB采集边界')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries={e['path']:e for e in missing};total=0
            for item in archive.infolist():
                parts=PurePosixPath(item.filename).parts
                if len(parts)<2 or '..' in parts or item.is_dir():continue
                path='/'.join(parts[1:]);e=entries.get(path)
                if not e or item.file_size>8_000_000 or e.get('mode')=='120000':continue
                if total+item.file_size>200_000_000:raise ValueError('采集原文累计超过200MB边界')
                blob=archive.read(item);total+=len(blob)
                if e.get('sha') and hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest()!=e['sha']:raise ValueError('归档文件与固定Git版本不一致')
                sha=digest(blob);dest=materials.folder/'sources'/sha;dest.parent.mkdir(parents=True,exist_ok=True)
                if not dest.exists():dest.write_bytes(blob)
                atomic(materials.folder/'file-index'/(digest(path)+'.json'),{'path':path,'sha256':sha,'commit':materials.commit,'kind':e['kind'],'representation':'original'})
        atomic(materials.folder/'archive-acquisition.json',{'sha256':digest(raw),'bytes':len(raw),'repo':materials.repo,'commit':materials.commit})
    except Exception as exc:
        materials.omissions.append({'path':'.','status':'partial_acquisition','reason':'归档采集未完成，逐文件复用同版本缓存：'+str(exc)[:350]})

def parse_file(workspace,path,text):
    language=language_for(path,text)
    if not language:return [],[],[],['未支持此语言的语法解析；仍可读取原文']
    original=text
    if path.endswith('.vue'):
        text,has,typed=vue_script(text);language='typescript' if typed else 'javascript'
        if not has:return [],[],[],['Vue没有脚本区；模板行为待按原文取证']
    parser=parser_for(workspace,language);data=text.encode('utf8');tree=parser.parse(data)
    definitions=[];calls=[];imports=[];stack=[(tree.root_node,None)]
    def value(n):return data[n.start_byte:n.end_byte].decode('utf8') if n else ''
    while stack:
        n,owner=stack.pop();next_owner=owner
        if n.type in DEFINITIONS:
            name_node=n.child_by_field_name('name')
            if not name_node and n.child_by_field_name('declarator'):
                name_node=n.child_by_field_name('declarator')
                while name_node.child_by_field_name('declarator'):name_node=name_node.child_by_field_name('declarator')
            if not name_node and n.parent and n.parent.type in ('variable_declarator','pair','assignment_expression'):name_node=n.parent.child_by_field_name('name') or n.parent.child_by_field_name('key') or n.parent.child_by_field_name('left')
            name=value(name_node) or '<anonymous>';body=n.child_by_field_name('body')
            body_text=value(body).strip();implementation='concrete'
            if body is None:implementation='declaration'
            elif language=='python':
                try:
                    body_nodes=ast.parse(value(n)).body[0].body
                    useful=[v for v in body_nodes if not (isinstance(v,ast.Expr) and isinstance(v.value,ast.Constant) and isinstance(v.value.value,str))]
                    if not useful or all(isinstance(v,ast.Pass) or (isinstance(v,ast.Expr) and isinstance(v.value,ast.Constant) and v.value.value is Ellipsis) or (isinstance(v,ast.Raise) and 'NotImplementedError' in ast.unparse(v)) for v in useful):implementation='abstract'
                except (SyntaxError,AttributeError):
                    children=[c for c in body.named_children if c.type!='comment']
                    if children and all(value(c).strip() in ('pass','...','raise NotImplementedError','raise NotImplementedError()') for c in children):implementation='abstract'
            elif body_text in ('{}','{ }',';'):implementation='empty'
            start=n.start_point.row+1;end=n.end_point.row+1;nid='syntax:'+digest([path,name,start,end])[:20]
            children=list(body.named_children) if body else []
            if language=='python' and children and children[0].type=='expression_statement' and children[0].named_children and children[0].named_children[0].type in ('string','concatenated_string'):
                children=children[1:]
            behavior_start=children[0].start_point.row+1 if children else start
            definitions.append({'id':nid,'label':'METHOD','path':path,'NAME':name,'FULL_NAME':path+'::'+name,'LINE_NUMBER':start,'LINE_NUMBER_END':end,'implementation_kind':implementation,'language':language,'behavior_start':behavior_start})
            next_owner=nid
        if n.type in CALLS:
            target=n.child_by_field_name('function') or n.child_by_field_name('name')
            if target:calls.append({'owner':owner,'name':value(target),'line':n.start_point.row+1,'path':path,'targets':[]})
        if 'import' in n.type or n.type in ('include_expression','require_expression'):
            imports.append({'path':path,'line':n.start_point.row+1,'text':value(n)[:500]})
        stack.extend((c,next_owner) for c in reversed(n.named_children))
    # Script files without definitions are legitimate entry candidates, not invented functions.
    if not definitions and language=='bash':
        definitions=[{'id':'syntax:'+digest(path)[:20],'label':'SCRIPT','path':path,'NAME':'<script>','FULL_NAME':path,'LINE_NUMBER':1,'LINE_NUMBER_END':len(original.splitlines()),'implementation_kind':'concrete','language':language}]
    return definitions,calls,imports,(['语法树包含错误节点，不能声称完整解析'] if tree.root_node.has_error else [])+(['Vue模板与运行时绑定未建立静态边'] if path.endswith('.vue') else [])

def import_bindings(path,text,paths):
    """Only explicit import spellings. Unknown aliases/package exports stay unresolved."""
    result={}
    if path.endswith('.py'):
        try:
            for n in ast.walk(ast.parse(text)):
                if isinstance(n,ast.ImportFrom):
                    dest=resolve(path,'.'*n.level+(n.module or ''),paths)
                    if dest:
                        for a in n.names:
                            if a.name!='*':result[a.asname or a.name]=(dest,a.name)
                elif isinstance(n,ast.Import):
                    for a in n.names:
                        dest=resolve(path,a.name,paths)
                        if dest:result[(a.asname or a.name)+'.']=(dest,None)
        except SyntaxError:pass
    elif PurePosixPath(path).suffix in ('.js','.jsx','.ts','.tsx','.vue','.mjs'):
        for m in re.finditer(r'import\s*\{([^}]+)\}\s*from\s*[\'\"]([^\'\"]+)[\'\"]',text):
            dest=resolve(path,m[2],paths)
            if dest:
                for entry in m[1].split(','):
                    names=re.fullmatch(r'\s*(\w+)(?:\s+as\s+(\w+))?\s*',entry)
                    if names:result[names[2] or names[1]]=(dest,names[1])
    return result

def isolated_parse(workspace,folder,rows,identity):
    """Native parser failures are file-local; completed files are durable checkpoints."""
    dest=folder/'parsed';dest.mkdir(exist_ok=True);results=[];pending=[]
    for row in rows:
        key=digest([identity,row['path'],row['sha256']]);target=dest/(key+'.json')
        if target.exists():results.append(json.loads(target.read_text(encoding='utf8')))
        else:pending.append({**row,'target':str(target)})
    worker=Path(__file__).with_name('kd_s3_index_worker.py')
    while pending:
        batch=pending[:32];request=folder/'parser-request.json';progress=folder/'parser-progress.json'
        atomic(request,{'workspace':str(workspace),'progress':str(progress),'rows':batch})
        atomic(progress,{})
        with (folder/'parser.log').open('ab') as log:
            try:
                run=subprocess.run([sys.executable,'-X','faulthandler','-X','utf8',str(worker),str(request)],stdout=log,stderr=log,timeout=120)
                failure=f'原生解析进程退出码 {run.returncode}' if run.returncode else None
            except subprocess.TimeoutExpired:failure='语法解析批次超时120秒'
        active=json.loads(progress.read_text(encoding='utf8'))
        completed=[r for r in batch if Path(r['target']).exists()]
        for row in completed:results.append(json.loads(Path(row['target']).read_text(encoding='utf8')))
        pending=[r for r in pending if r not in completed]
        if failure:
            affected=[r for r in batch if r['path']==active.get('path') and r in pending]
            if not affected:affected=[r for r in batch if r in pending]
            for row in affected:
                result={'path':row['path'],'definitions':[],'calls':[],'imports':[],'limits':[failure+'；保留原文，未声称完成此文件解析']}
                atomic(Path(row['target']),result);results.append(result);pending.remove(row)
        elif any(r in pending for r in batch):raise ValueError('解析器正常退出却缺少文件结果')
    return results

def build(materials,workspace,note=lambda _:None):
    start=time.monotonic();folder=materials.folder/'code-index';folder.mkdir(parents=True,exist_ok=True)
    identity={'repo':materials.repo,'commit':materials.commit,'tool':tool_identity(workspace),'adapter':digest([Path(__file__).read_bytes().hex(),Path(__file__).with_name('kd_s3_index_worker.py').read_bytes().hex()])}
    cache=folder/'manifest.json'
    if not materials.tree:materials.inventory()
    if cache.exists():
        meta=json.loads(cache.read_text(encoding='utf8'))
        if meta['identity']!=identity:raise ValueError('代码索引缓存版本不匹配')
        if digest((folder/'index.json').read_bytes())!=meta['files']['index.json']:raise ValueError('代码索引哈希不匹配')
        return json.loads((folder/'index.json').read_text(encoding='utf8')),meta
    hydrate_archive(materials,note);acquisition=time.monotonic()-start
    methods=[];calls=[];imports=[];omissions=[];bindings={};paths={e['path'] for e in materials.tree};parse_rows=[]
    for entry in materials.tree:
        path=entry['path']
        if EXCLUDED.intersection(PurePosixPath(path).parts) or entry.get('mode')=='120000':continue
        suffix=PurePosixPath(path).suffix.lower()
        if suffix not in LANG and suffix!='':
            if entry.get('kind')=='implementation':omissions.append({'path':path,'status':'unsupported_parser','reason':'此语言未安装语法解析器，仍可按原文定位'})
            continue
        read_start=time.monotonic();source=materials.read(path);acquisition+=time.monotonic()-read_start
        if not source:omissions.append({'path':path,'status':'not_read','reason':'原文不可读'});continue
        text='\n'.join(source['lines']);reason=generated_reason(path,text)
        if reason:
            omissions.append({'path':path,'status':'deferred_generated','reason':reason+'：保留来源与文件入口，暂不展开内嵌定义；必要时按引用读取'})
            methods.append({'id':'syntax:'+digest(path)[:20],'label':'SCRIPT','path':path,'NAME':'<distribution>','FULL_NAME':path,'LINE_NUMBER':1,'LINE_NUMBER_END':len(source['lines']),'implementation_kind':'distribution','language':language_for(path,text)})
            continue
        bindings[path]=import_bindings(path,text,paths)
        parse_rows.append({'path':path,'sha256':source['sha256'],'source':str(materials.folder/'sources'/source['sha256'])})
    for result in isolated_parse(workspace,folder,parse_rows,identity):
        methods.extend(result['definitions']);calls.extend(result['calls']);imports.extend(result['imports'])
        omissions.extend({'path':result['path'],'status':'unresolved','reason':v} for v in result['limits'])
    # Only unique lexical same-file resolution; receiver/dynamic/cross-file calls stay explicit unknowns.
    byname=collections.defaultdict(list)
    for m in methods:byname[(m['path'],m['NAME'])].append(m['id'])
    edges=[]
    for c in calls:
        candidates=byname.get((c['path'],c['name']),[])
        resolution='unique_lexical_same_file'
        if not candidates:
            binding=bindings.get(c['path'],{}).get(c['name'])
            if not binding:
                for alias,target in bindings.get(c['path'],{}).items():
                    if alias.endswith('.') and c['name'].startswith(alias) and '.' not in c['name'][len(alias):]:binding=(target[0],c['name'][len(alias):]);break
            if binding:candidates=byname.get(binding,[]);resolution='explicit_import_symbol_candidate'
        if c['owner'] and len(candidates)==1:
            c['targets']=candidates;edges.append({'source':c['owner'],'target':candidates[0],'label':'METHOD_CALL','line':c['line'],'resolution':resolution})
    # Parsed per-file checkpoints retain all call occurrences. The working index
    # only needs distinct location relationships; no duplicated full definition list.
    unique_edges={}
    for e in edges:
        key=(e['source'],e['target'],e['resolution'])
        item=unique_edges.setdefault(key,{**e,'lines':[]})
        if e['line'] not in item['lines']:item['lines'].append(e['line'])
    edges=list(unique_edges.values())
    unresolved={}
    for c in calls:
        if c['targets']:continue
        key=(c['owner'],c['path'],c['name'])
        item=unresolved.setdefault(key,{'owner':c['owner'],'path':c['path'],'name':c['name'],'lines':[]})
        if c['line'] not in item['lines']:item['lines'].append(c['line'])
    graph={'nodes':[{'id':m['id'],'label':m['label'],'path':m['path']} for m in methods],
        'methods':methods,'edges':edges,'unresolved_calls':list(unresolved.values()),
        'imports':list({digest(i):i for i in imports}.values()),'omissions':materials.omissions+omissions,
        'limits':['轻量语法与符号索引，不是完整语义调用图或运行验证','显式导入仅提供实现候选；重绑定、接收者、动态调用和跨语言调用未证明','代码定义用于定位；业务功能与步骤必须有原文依据']}
    atomic(folder/'index.json',graph)
    meta={'identity':identity,'files':{'index.json':digest((folder/'index.json').read_bytes())},'mode':'syntax-symbols','nodes':len(methods),'methods':len(methods),'edges':len(edges),'unresolved_calls':sum(not c['targets'] for c in calls),'index_bytes':(folder/'index.json').stat().st_size,'acquisition_seconds':acquisition,'graph_seconds':time.monotonic()-start-acquisition,'global_dataflow':False}
    atomic(cache,meta);return graph,meta
