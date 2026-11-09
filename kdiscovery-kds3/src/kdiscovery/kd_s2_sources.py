"""Deterministic, immutable GitHub material inventory and evidence windows."""
import ast
import hashlib
import json
import re
import os
import time
import uuid
import httpx
import base64
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from .kd_materials import material_kind
from .kd_s2_format import digest
from .kd_s2_architecture import inspect, resolve, module_key, entry_score, CODE


def longpath(path):
    path = Path(path).resolve()
    if os.name == 'nt' and not str(path).startswith('\\\\?\\'):
        return Path('\\\\?\\' + str(path))
    return path


def kind(path):
    if PurePosixPath(path).name.lower().startswith(('license', 'copying', 'notice')): return 'document'
    if PurePosixPath(path).name.lower() in ('readme', 'readme.markdown'): return 'document'
    return material_kind(path)


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        for attempt in range(6):
            try:temp.replace(path);break
            except PermissionError:
                if attempt==5:raise
                time.sleep(.02*(2**attempt))
    finally:
        if temp.exists():temp.unlink()


def notebook_text(raw):
    data = json.loads(raw)
    # Outputs are neither input evidence nor a test performed by this mining run.
    return '\n'.join('# cell ' + str(i + 1) + ' (' + c.get('cell_type', '') + ')\n' +
        (''.join(c.get('source', [])) if isinstance(c.get('source'), list) else c.get('source', ''))
        for i, c in enumerate(data.get('cells', [])))


class Materials:
    def __init__(self, workspace, folder, repo, commit, api, existing=None):
        self.workspace, self.folder = Path(workspace), longpath(folder)
        self.repo, self.commit, self.api = repo, commit, api
        self.existing = existing or {}
        self.files = {}; self.omissions = []; self.tree = []
        self.remote_error = None
        self.architecture = {}; self.window_tails = {}; self.read_failures = set()
        self.packages = {}
        self.raw_network_failed = False; self.network_failures = 0
        self.prior_files = None
        self.evidence_plans = {}

    def saved_source(self, path):
        """Reuse only immutable original bytes at this exact repository/commit.

        Never load an old overview, SOP or extraction as new source evidence.
        Git blob verification in read() also checks the current fixed tree.
        """
        if self.prior_files is None:
            self.prior_files={}
            from .kd_s2_paths import project_folder
            commit_root=longpath(project_folder(self.workspace,self.repo)/'KD-S-2'/self.commit)
            if commit_root.exists():
                for marker in sorted(commit_root.glob('*/file-index/*.json')):
                    try:
                        meta=json.loads(marker.read_text(encoding='utf-8'))
                        if meta.get('commit')!=self.commit or not re.fullmatch('[0-9a-f]{64}',meta.get('sha256','')):continue
                        self.prior_files.setdefault(meta['path'],[]).append((marker.parent.parent/'sources'/meta['sha256'],meta['sha256']))
                    except (ValueError,KeyError,OSError):continue
        for source,sha in self.prior_files.get(path,[]):
            try:
                raw=source.read_bytes()
                if digest(raw)==sha:return raw
            except OSError:continue
        return None

    def cached(self, url, params=None):
        """A commit-addressed body stays immutable after the generic cache TTL.

        The credential identity and exact URL must still match. This never reuses
        a branch/head response, a different repository, or an anonymous cache.
        """
        if not hasattr(self.api, 'store') or not hasattr(self.api, 'identity'): return None
        identity = self.api.identity()[1]
        address = str(httpx.URL(url, params=params))
        key = hashlib.sha256((identity + address).encode()).hexdigest()
        with self.api.store.connect() as db:
            row = db.execute('SELECT body FROM github_cache WHERE key=?', (key,)).fetchone()
        return bytes(row[0]) if row else None

    def inventory(self):
        path = self.folder / 'inventory.json'
        if path.exists(): data = json.loads(path.read_text(encoding='utf-8'))
        else:
            url = f'https://api.github.com/repos/{self.repo}/git/trees/{self.commit}'
            cached = self.cached(url, {'recursive': 1})
            data = json.loads(cached) if cached is not None else self.api.get(url, params={'recursive': 1}).json()
            atomic(path, data)
        if data.get('truncated'): self.omissions.append({'path': '.', 'reason': 'GitHub 文件树截断，未列出部分未经检查'})
        for entry in data.get('tree', []):
            if entry.get('type') != 'blob': continue
            p = entry['path']; category = kind(p)
            if not category:
                self.omissions.append({'path': p, 'reason': '不支持格式或排除生成/第三方目录'}); continue
            if entry.get('size', 0) > 8_000_000:
                self.omissions.append({'path': p, 'reason': '单文件超过8MB采集边界，需另行分段获取', 'status':'not_read'}); continue
            self.tree.append({**entry, 'kind': category})
        return self.tree

    def read(self, path):
        if path in self.files: return self.files[path]
        if path not in {e['path'] for e in self.tree}: return None
        marker = self.folder / 'file-index' / (digest(path) + '.json')
        if marker.exists():
            meta = json.loads(marker.read_text(encoding='utf-8'))
            raw = (self.folder / 'sources' / meta['sha256']).read_bytes()
            if meta.get('commit') != self.commit or digest(raw) != meta['sha256']: raise ValueError('来源缓存版本或内容校验失败')
        else:
            raw = self.saved_source(path)
            old = self.existing.get(path, {})
            local = old.get('local_path')
            if raw is None and local:
                p = (self.workspace / local).resolve()
                if p.is_relative_to(self.workspace.resolve()) and p.is_file():
                    candidate = p.read_bytes()
                    expected = next(e.get('sha') for e in self.tree if e['path'] == path)
                    blob = hashlib.sha1(b'blob ' + str(len(candidate)).encode() + b'\0' + candidate).hexdigest()
                    if old.get('sha256') == digest(candidate) and (not expected or expected == blob): raw = candidate
            if raw is None:
                url = f'https://raw.githubusercontent.com/{self.repo}/{self.commit}/{quote(path, safe="/")}'
                raw = self.cached(url)
                if raw is None:
                    if path in self.read_failures or self.network_failures >= 3:
                        self.omissions.append({'path': path, 'reason': '本地缺少该版本正文，远程采集因网络不可用未完成', 'status': 'not_read'})
                        return None
                    try:
                        if self.raw_network_failed:
                            from .github_client import GithubUnavailable
                            raise GithubUnavailable('raw 主机不可用，改读固定 git blob', 'network')
                        raw = self.api.get(url).content
                    except Exception as exc:
                        if getattr(exc, 'kind', None) != 'network': raise
                        self.raw_network_failed = True
                        sha = next(e.get('sha') for e in self.tree if e['path'] == path)
                        try:
                            if not sha: raise exc
                            blob = self.api.get(f'https://api.github.com/repos/{self.repo}/git/blobs/{sha}').json()
                            if blob.get('encoding') != 'base64': raise ValueError('Git blob不是base64正文')
                            raw = base64.b64decode(blob['content'])
                            self.network_failures = 0
                        except Exception as fallback:
                            if getattr(fallback, 'kind', None) not in (None, 'network'): raise
                            self.remote_error = str(fallback); self.read_failures.add(path)
                            self.network_failures += 1
                            self.omissions.append({'path': path, 'reason': self.remote_error, 'status': 'not_read'})
                            return None
            expected = next(e.get('sha') for e in self.tree if e['path'] == path)
            if expected and hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() != expected:
                self.omissions.append({'path': path, 'reason': '正文与固定版本 Git blob 哈希不一致', 'status': 'conflicting'})
                return None
            if len(raw) > 8_000_000:
                self.omissions.append({'path': path, 'reason': '正文超过8MB采集边界', 'status':'not_read'}); return None
            sha = digest(raw)
            target = self.folder / 'sources' / sha; target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                temp = target.with_name(target.name + '.tmp'); temp.write_bytes(raw); temp.replace(target)
            meta = {'path': path, 'sha256': sha, 'commit': self.commit, 'kind': kind(path)}
            atomic(marker, meta)
        try:
            text = raw.decode('utf-8-sig')
            if '\x00' in text: raise ValueError('二进制内容')
            if path.lower().endswith('.ipynb'): text = notebook_text(text)
        except (UnicodeError, ValueError):
            self.omissions.append({'path': path, 'reason': '无法读取文本或Notebook格式'}); return None
        value = {**meta, 'lines': text.splitlines(), 'representation': 'notebook_inputs' if path.endswith('.ipynb') else 'original'}
        self.files[path] = value
        return value

    def scan(self, paths):
        for path in paths:
            if path in self.architecture: continue
            f = self.read(path)
            if f:
                self.architecture[path] = {**inspect(path, f['lines']), 'module': module_key(path), 'sha256': f['sha256']}
        atomic(self.folder / 'source-index.json', self.architecture)

    def scout(self):
        """Bounded acquisition distributed across modules, without a model call."""
        self.package_index()
        checkpoint = self.folder / 'scout.json'
        if checkpoint.exists():
            selected = json.loads(checkpoint.read_text(encoding='utf-8'))['paths']
        else:
            groups = {}
            for e in self.tree:
                if e['kind'] in ('implementation', 'interface'):
                    groups.setdefault(module_key(e['path']), []).append(e)
            for group in groups.values(): group.sort(key=lambda e: (-entry_score(e['path']), e['path']))
            selected = []; size = 0
            for i in range(max((len(g) for g in groups.values()), default=0)):
                for key in sorted(groups):
                    if i >= len(groups[key]): continue
                    e = groups[key][i]
                    if len(selected) >= 96 or size + e.get('size', 2000) > 2_000_000: continue
                    selected.append(e['path']); size += e.get('size', 2000)
                if len(selected) >= 96: break
            atomic(checkpoint, {'paths': selected, 'acquisition_limit': '96 files / 2 MB; remaining paths are not inspected'})
        self.scan(selected)
        self.omissions += [{'path': e['path'], 'status': 'not_read', 'reason': '架构初扫尚未读取，后续按功能缺口定位'}
                           for e in self.tree if e['kind'] in ('implementation', 'interface') and e['path'] not in self.architecture]
        return [{'path': p, 'module': v['module'], 'symbols': [d['name'] for d in v['definitions']],
                 'entry_lines': [e['line'] for e in v['entries']], 'imports': v['imports'], 'limitations': v['limitations']}
                for p, v in self.architecture.items()]

    def package_index(self):
        for e in self.tree:
            if PurePosixPath(e['path']).name != 'package.json' or e['path'].count('/') > 3: continue
            f = self.read(e['path'])
            if f:
                try:
                    package = json.loads('\n'.join(f['lines']))
                    if isinstance(package.get('name'), str): self.packages[package['name']] = str(PurePosixPath(e['path']).parent)
                except ValueError: pass

    def normalize_hints(self, hints):
        paths = {e['path'] for e in self.tree}; result = []
        for hint in hints:
            if not isinstance(hint, str): continue
            result.append(hint)
            # Models sometimes annotate a valid path with a line or symbol.
            clean = re.split(r'\s+\(|[:#]', hint, maxsplit=1)[0]
            if clean in paths and clean != hint:
                result.append(clean)
                suffix=hint[len(clean):].lstrip(':# ')
                symbol=re.match(r'([A-Za-z_$][\w$]*)',suffix)
                if symbol:result.append(symbol[1])
        return list(dict.fromkeys(result))

    def evidence(self, groups, limit=36000, continuation=False):
        """Each feature gets primary evidence before any other feature's helpers."""
        merged = {}; share = max(256, limit // max(1, len(groups)))
        for clues in groups:
            clues = self.normalize_hints(clues)
            primary = self.select(clues)[:3]
            paths = self.follow(primary, depth=3 if continuation else 2)
            proof = self.windows(paths, clues, limit=share, continuation=continuation)
            for path, source in proof.items():
                prior = merged.get(path, {**source, 'lines': []})
                prior['lines'] = sorted({l['line']: l for l in prior['lines'] + source['lines']}.values(), key=lambda l: l['line'])
                merged[path] = prior
        return merged

    def uncovered_modules(self, features):
        """Audit candidates, never assertions that a directory is a capability."""
        covered = set()
        paths = {e['path'] for e in self.tree}
        for f in features:
            for h in self.normalize_hints(f['locators']):
                if h in paths: covered.add(module_key(h))
        candidates = {}
        for path, entry in self.architecture.items():
            module = entry['module']
            if module in covered or module in candidates: continue
            if not entry['entries'] and not (PurePosixPath(path).stem == 'index' and entry['imports']): continue
            locators = [path]
            locators += [target for imp in entry['imports'] if (target := resolve(path, imp['module'], paths))]
            candidates[module] = {'key': 'module-audit-' + digest(module)[:12], 'name': '待核实入口：' + module,
                'goal': '核查此模块对终端使用者或集成开发者提供的业务能力；只能根据原文确认功能，模块名和框架不能作为能力依据。',
                'locators': locators, 'discovery_probe': True}
        return list(candidates.values())

    def follow(self, paths, depth=2):
        all_paths = {e['path'] for e in self.tree}; seen = set(paths); frontier = list(paths); found = []
        for _ in range(depth):
            self.scan(frontier); following = []
            for p in frontier:
                for imp in self.architecture.get(p, {}).get('imports', []):
                    target = resolve(p, imp['module'], all_paths)
                    if not target:
                        for name, base in self.packages.items():
                            if imp['module'].startswith(name + '/'):
                                target = resolve(base + '/__entry__.js', './' + imp['module'][len(name) + 1:], all_paths)
                                if target: break
                    if target and target not in seen:
                        seen.add(target); found.append(target); following.append(target)
                    elif not target and imp['module'].startswith('.'):
                        self.omissions.append({'path': p, 'status': 'unknown', 'reason': '本仓库引用未定位：' + imp['module']})
            frontier = following
            if not frontier: break
        return list(dict.fromkeys(paths + found))

    def select(self, hints=(), initial=False, groups=None):
        hints = self.normalize_hints(hints)
        def score(entry, clues):
            terms = set(re.findall(r'[\w-]{3,}', ' '.join(clues).lower())) - {'src', 'lib', 'packages', 'modules', 'services', 'pages'}
            p = entry['path'].lower(); name = PurePosixPath(p).name
            base = {'document': 6, 'example': 5, 'interface': 4, 'test': 2, 'implementation': 1, 'runtime': 0, 'engineering': -1}.get(entry['kind'], 0)
            explicit = 100 if entry['path'] in clues else 80 if any(p.startswith(h.lower().rstrip('/') + '/') for h in clues if '/' in h) else 0
            symbols = ' '.join(d['name'].lower() for d in self.architecture.get(entry['path'], {}).get('definitions', []))
            bonus = sum(12 for t in terms if t in symbols)
            irrelevant = 100 if p.startswith('.github/issue_template') or 'pull_request_template' in p else 0
            return explicit + sum(8 for t in terms if t in p) + bonus + base + (20 if initial and name.startswith('readme') and p.count('/') < 2 else 0) - irrelevant
        if groups:
            queues = [sorted(self.tree, key=lambda e: (-score(e, clues), e['path'])) for clues in groups]
            ranked = []; seen = set()
            for i in range(len(self.tree)):
                for queue in queues:
                    entry = queue[i]
                    if entry['path'] not in seen: ranked.append(entry); seen.add(entry['path'])
        else:
            ranked = sorted(self.tree, key=lambda e: (-score(e, hints), e['path']))
        chosen = []; estimate = 0
        for entry in ranked:
            if estimate >= 42000: break
            chosen.append(entry)
            estimate += min(max(entry.get('size', 2000), 256), 10000)
        for e in ranked[len(chosen):]:
            self.omissions.append({'path': e['path'], 'reason': '本批材料容量未选入，未视为已检查'})
        return [e['path'] for e in chosen]

    def overview_directory(self, limit=16000):
        # Give each top-level/module directory representation instead of paying
        # for thousands of near-identical leaf paths before any source analysis.
        buckets = {}
        for e in self.tree:
            parts = e['path'].split('/')
            group = '/'.join(parts[:min(4, max(1, len(parts) - 1))])
            buckets.setdefault(group, []).append(e)
        output = []; size = 0
        for key in sorted(buckets, key=lambda k: (k.count('/'), k)):
            entries = buckets[key]
            item = {'path': key, 'files': len(entries), 'kinds': sorted({e['kind'] for e in entries})}
            size += len(json.dumps(item, ensure_ascii=False))
            if size > limit: break
            output.append(item)
        self.omissions.append({'path': '.', 'reason': '概览使用目录摘要；完整目录仅供程序按缺口定位，未列出的路径不视为已检查', 'status': 'not_read'})
        return output

    def windows(self, paths, hints=(), limit=42000, continuation=False):
        output = {}; remaining = limit
        terms = [t for t in hints if isinstance(t, str) and len(t) >= 3]
        for at, path in enumerate(paths):
            if remaining < 256:
                self.omissions.extend({'path': p, 'reason': '本批原文容量不足，未读取'} for p in paths[at:])
                break
            f = self.read(path)
            if not f: continue
            lines = f['lines']; hits = [i for i, line in enumerate(lines) if any(t.lower() in line.lower() for t in terms)]
            blocks = []
            if PurePosixPath(path).suffix in CODE:
                self.scan([path])
                blocks = [(d['start'] - 1, d['end']) for d in self.architecture.get(path, {}).get('definitions', [])
                          if any(d['start'] - 1 <= i < d['end'] for i in hits)]
                # Include directly called local helpers, not just the entry symbol.
                selected_text = '\n'.join(lines[i] for a,b in blocks for i in range(a, min(b,len(lines))))
                called = set(re.findall(r'\b([A-Za-z_$][\w$]*)\s*\(', selected_text))
                blocks += [(d['start'] - 1,d['end']) for d in self.architecture.get(path,{}).get('definitions',[]) if d['name'] in called]
            if path.endswith('.py'):
                try:
                    tree = ast.parse('\n'.join(lines))
                    blocks = [(n.lineno - 1, n.end_lineno) for n in ast.walk(tree)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and any(n.lineno - 1 <= i < n.end_lineno for i in hits)]
                except SyntaxError: pass
            if not blocks:
                # Expand Markdown/RST headings to their full section when possible.
                headings = [i for i, line in enumerate(lines) if re.match(r'^#{1,6}\s+', line) or (i + 1 < len(lines) and re.fullmatch(r'[=~-]{3,}', lines[i + 1]))]
                if headings and hits:
                    for hit in hits[:6]:
                        start = max([i for i in headings if i <= hit], default=0)
                        end = min([i for i in headings if i > hit], default=len(lines))
                        blocks.append((start, end))
                else:
                    blocks = [(max(0, i - 25), min(len(lines), i + 65)) for i in hits[:6]] or [(0, min(len(lines), 200))]
            indexes = sorted({i for a, b in blocks for i in range(a, min(b, len(lines)))})
            if continuation and path in self.window_tails:
                indexes = [i for i in indexes if i >= self.window_tails[path]]
            chosen = []; size = 0
            for i in indexes:
                cost = len(lines[i]) + 1
                if size + cost > min(10000, remaining): break
                chosen.append({'line': i + 1, 'text': lines[i]}); size += cost
            if chosen:
                output[path] = {k: f[k] for k in ('sha256', 'kind', 'representation')}
                output[path].update(lines=chosen, total_lines=len(lines)); remaining -= size
                if chosen[-1]['line'] < (max(indexes) + 1 if indexes else 0):
                    self.window_tails[path] = chosen[-1]['line']
                    self.omissions.append({'path': path, 'status': 'not_read', 'next_line': chosen[-1]['line'] + 1, 'reason': '定义块尚未读完，保存续读位置'})
            if len(chosen) < len(lines): self.omissions.append({'path': path, 'reason': '仅检查所选章节或定义片段，其余正文尚未检查'})
            if remaining <= 0: break
        return output
