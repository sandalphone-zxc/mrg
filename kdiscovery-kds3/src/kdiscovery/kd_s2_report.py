"""Self-contained read-only reports, no model narration or remote scripts."""
import html
import json
from pathlib import Path
from .kd_s2_format import digest
from .kd_s2_sources import atomic


def graph(nodes, edges, label):
    esc = lambda x: html.escape(str(x), quote=True)
    pos = {n['id']: (30 + i % 3 * 290, 30 + i // 3 * 130) for i, n in enumerate(nodes)}
    height = max(150, ((len(nodes) + 2) // 3) * 130 + 30)
    svg = f'<svg role="img" aria-label="{esc(label)}" viewBox="0 0 900 {height}">'
    for e in edges:
        if e['source'] not in pos or e['target'] not in pos: continue
        a, b = pos[e['source']], pos[e['target']]
        svg += f'<path d="M{a[0]+115},{a[1]+65} L{b[0]+115},{b[1]}" stroke="#64748b" fill="none" marker-end="url(#arrow)"><title>{esc(e.get("meaning", "包含"))}</title></path>'
    for n in nodes:
        x,y = pos[n['id']]
        label = str(n['name']); lines = [label[:16], label[16:32] + ('…' if len(label) > 32 else '')]
        text = ''.join(f'<tspan x="{x+10}" y="{y+27+i*20}">{esc(line)}</tspan>' for i,line in enumerate(lines) if line)
        svg += f'<a href="#{esc(n["id"])}"><rect x="{x}" y="{y}" width="240" height="65" rx="9" fill="#eef5ff" stroke="#517fac"/><text font-size="13">{text}</text><title>{esc(n.get("purpose", n["name"]))}</title></a>'
    return svg + '</svg>'


def report(mrg, coverage, usage, evidence=None, implementations=None):
    esc = lambda x: html.escape(str(x))
    def details(title, value):
        return '<details><summary>' + esc(title) + '</summary><pre>' + esc(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre></details>'
    cards = []
    scope_rows=''.join('<tr><td>'+esc(v.get('name',''))+'</td><td>'+esc(v.get('contract_status','未确认'))+'</td><td>'+esc(v.get('scope_status','未核对'))+'</td><td>'+str(v.get('pages_read',0))+' / '+str(v.get('pages_total','未记录'))+'</td></tr>' for v in coverage.get('feature_ledger',[]))
    scope_table='<section><h2>候选覆盖进度</h2><p>确认一个局部功能不代表整个候选已覆盖；页数只表示材料处理进度。</p><table><thead><tr><th>候选</th><th>能力契约</th><th>候选范围</th><th>已处理 / 全部证据页</th></tr></thead><tbody>'+scope_rows+'</tbody></table></section>'
    for sop in mrg['SOP']:
        nodes = [n for k in ('OMN', 'MN') for n in mrg[k] if n['sop_id'] == sop['id']]
        edges = [e for e in mrg['ME'] if e['owner_sop_id'] == sop['id']]
        records = (evidence or {}).get('records', [])
        node_details = ''.join('<div id="' + esc(n['id']) + '">' + details(n['name'], n) + details('本步骤来源', [e for e in records if e['target_id'] == n['id']]) + '</div>' for n in nodes)
        cards.append('<article id="' + esc(sop['id']) + '"><h2>' + esc(sop['name']) + '</h2><p>' + esc(sop['purpose']) + '</p>' +
            '<p>输入：' + esc('；'.join(p['meaning'] for p in sop['inputs'])) + '</p><p>输出：' + esc('；'.join(p['meaning'] for p in sop['outputs'])) + '</p>' +
            ('<p>内部步骤尚未细化；功能描述仍保留。</p>' if not nodes else '') +
            graph(nodes, edges, sop['name'] + '内部流程') + node_details + details('内部关系', edges) + details('功能完整定义', sop) + details('本功能来源', [e for e in records if e['target_id'] == sop['id']]) + '</article>')
    positions = {s['id']: (30 + (i % 3) * 285, 35 + (i // 3) * 135) for i, s in enumerate(mrg['SOP'])}
    svg = '<svg role="img" aria-label="功能业务关系" viewBox="0 0 900 ' + str(max(160, ((len(positions) + 2) // 3) * 135 + 50)) + '"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3z" fill="#65728b"/></marker></defs>'
    for e in mrg['ME']:
        if e['level'] != 'function' or e['source'] not in positions or e['target'] not in positions: continue
        a, b = positions[e['source']], positions[e['target']]
        svg += f'<path d="M {a[0]+115} {a[1]+65} L {b[0]+115} {b[1]}" stroke="#65728b" fill="none" marker-end="url(#arrow)"><title>{esc(e["meaning"])}</title></path>'
    for sop in mrg['SOP']:
        x, y = positions[sop['id']]
        svg += f'<a href="#{esc(sop["id"])}"><rect x="{x}" y="{y}" width="235" height="65" rx="9" fill="#e7f0fa" stroke="#5680ad"/><text x="{x+12}" y="{y+36}" font-size="14">{esc(sop["name"][:18])}</text><title>{esc(sop["purpose"])}</title></a>'
    svg += '</svg>'
    svg += '<h2>功能归属（包含关系，不代表先后顺序）</h2>' + graph(mrg['SOP'], [{'source': s['parent_sop_id'], 'target': s['id'], 'meaning': '包含'} for s in mrg['SOP'] if s['parent_sop_id']], '功能归属树') + scope_table
    enrichment=coverage.get('enrichment')
    execution=coverage.get('execution')
    if execution:
        svg += '<section><h2>本轮执行与内容覆盖</h2><p>本轮：'+esc('服务暂停' if execution.get('round_state')=='service_paused' else '已结束')+'；补充工作包：已复核 '+str(execution.get('packages_reviewed',0))+'，失败 '+str(execution.get('packages_failed',0))+'，未处理 '+str(execution.get('packages_pending',0))+'。</p><p>本轮结束不表示全项目完整。功能间关系 '+str(sum(e['level']=='function' for e in mrg['ME']))+' 条；功能内部关系 '+str(sum(e['level']=='internal' for e in mrg['ME']))+' 条。没有连线不表示独立。</p>'+details('覆盖状态',execution)+'</section>'
    if enrichment:
        labels={'reviewed':'已复核本包','budget_pending':'预算待继续','not_read':'证据未读取','failed':'补充失败，原成果保留','pending':'待处理'}
        entries=[]
        for kind,title in [('details','契约与内部路径'),('relations','功能依赖')]:
            for item in enrichment.get(kind,[]):
                entries.append('<tr><td>'+title+'</td><td>'+esc(item.get('id') or ' / '.join(item.get('ids',[])))+'</td><td>'+esc(labels.get(item['status'],item['status']))+'</td></tr>')
        svg += '<section><h2>初步成果后的补充进度</h2><p>复核范围限于已检查工作包；没有连线不表示独立，已受理任务不等于最终交付。预算不足保留待办。</p><table><tr><th>补充项</th><th>涉及功能</th><th>状态</th></tr>'+''.join(entries)+'</table></section>'
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KD-S-2 挖掘结果</title><style>body{font:16px/1.65 system-ui;color:#243249;background:#f5f7fa;max-width:1120px;margin:auto;padding:28px}article,section{background:white;padding:20px;margin:18px 0;border-radius:12px}h1{font-size:26px}h2{font-size:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}summary{cursor:pointer;font-weight:600}svg{width:100%}.note{color:#5c6675}</style>''' + '<h1>' + esc(mrg['MNS']['name']) + '</h1><p>' + esc(mrg['MNS']['goal']) + '</p><p class="note">KD-S-2 · 新需求格式，尚未接入当前需求工作台。来源定位不代表运行验证。</p><section><b>本轮状态：' + esc(coverage['status']) + '</b><p>功能 ' + str(len(mrg['SOP'])) + ' 项；内部操作 ' + str(len(mrg['OMN'])) + ' 项；状态/结果 ' + str(len(mrg['MN'])) + ' 项。</p>' + details('项目需求概览', mrg['MNS']) + details('模型用量', usage) + '</section><section><h2>功能关系</h2><p class="note">位置仅用于排版，没有连线的功能不代表可以并行。</p>' + svg + details('功能归属树', [{'id': s['id'], 'name': s['name'], 'parent': s['parent_sop_id']} for s in mrg['SOP']]) + details('业务关系完整说明', mrg['ME']) + '</section>' + ''.join(cards) + '<section>' + details('证据缺口与待明确事项', mrg['open_items']) + details('候选覆盖与失败诊断', coverage) + details('逐字段证据与原文定位', evidence or {}) + details('实现对应（未运行验证）', implementations or {}) + '</section></html>'


def publish(folder, identity, mrg, evidence, implementations, coverage, usage, sources):
    previous = folder / 'manifest.json'
    if previous.exists():
        old = verify(folder)
        archive = folder / 'history' / digest(old)
        archive.mkdir(parents=True, exist_ok=True)
        for name in [*old['files'], 'manifest.json']:
            target = archive / name
            if not target.exists(): target.write_bytes((folder / name).read_bytes())
        old_mrg = json.loads((folder / 'mrg.json').read_text(encoding='utf-8'))
        if old_mrg['SOP'] and not mrg['SOP']:
            atomic(folder / 'last-failed-attempt.json', {'coverage': coverage, 'usage': usage, 'identity': identity})
            return {'format': identity['format'], 'status': coverage['status'], 'folder': str(folder), 'manifest': old, 'preserved_previous': True}
    files = {'mrg.json': mrg, 'evidence.json': {'records': evidence, 'sources': [{k: f[k] for k in ('path', 'sha256', 'commit', 'kind', 'representation')} for f in sources.values()]},
        'implementation-map.json': {'runtime_verified': False, 'records': implementations}, 'coverage.json': coverage,
        'usage.json': {'requests_this_round': usage['requests'], 'cache_hits': usage['cache_hits'],
            'new_source_characters': sum(usage['visible'].values()), 'calls': usage['calls'], 'token_usage': '见任务用量账本；服务返回前未知，不按零处理'}}
    for name, value in files.items(): atomic(folder / name, value)
    text = report(mrg, coverage, files['usage.json'], files['evidence.json'], files['implementation-map.json'])
    temp = folder / 'report.html.tmp'; temp.write_text(text, encoding='utf-8'); temp.replace(folder / 'report.html')
    manifest = {**identity, 'strategy': 'KD-S-2', 'status': coverage['status'], 'runtime_verified': False,
        'files': {name: digest((folder / name).read_bytes()) for name in [*files, 'report.html', *(['format-definition.json'] if (folder / 'format-definition.json').exists() else [])]}}
    atomic(folder / 'manifest.json', manifest)
    return {'format': identity['format'], 'status': coverage['status'], 'folder': str(folder), 'manifest': manifest}


def verify(folder):
    folder = Path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    required = {'mrg.json', 'evidence.json', 'implementation-map.json', 'coverage.json', 'usage.json', 'report.html'}
    if manifest.get('format') != 'mrg-requirements-v1' or not required <= manifest.get('files', {}).keys():
        raise ValueError('不是完整的新格式清单')
    for name, sha in manifest['files'].items():
        if Path(name).name != name or digest((folder / name).read_bytes()) != sha:
            raise ValueError('结果文件校验失败：' + name)
    if 'format-definition.json' in manifest['files'] and manifest['files']['format-definition.json'] != manifest['schema_hash']:
        raise ValueError('成果格式定义与冻结指纹不一致')
    evidence = json.loads((folder / 'evidence.json').read_text(encoding='utf-8'))
    for source in evidence['sources']:
        sha = source['sha256']
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha): raise ValueError('来源哈希无效')
        if digest((folder / 'sources' / sha).read_bytes()) != sha: raise ValueError('来源材料校验失败')
    return manifest
