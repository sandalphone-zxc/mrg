"""Conservative source landmarks, not claims about implemented business features.

No repository code is imported or executed. JS scanning deliberately reports
unresolved dynamic dispatch rather than claiming a complete call graph.
"""
import ast
import posixpath
import re
from pathlib import PurePosixPath
from .kd_s2_spans import body_start

CODE = {'.py', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.vue'}


def mask(text):
    # Preserve offsets/newlines while ignoring braces in comments and strings.
    pattern = r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`'
    return re.sub(pattern, lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), text)


def inspect(path, lines):
    text = '\n'.join(lines); suffix = PurePosixPath(path).suffix.lower()
    definitions, imports, entries = [], [], []
    if suffix == '.py':
        try:
            tree = ast.parse(text)
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    definitions.append({'name': n.name, 'start': n.lineno, 'end': n.end_lineno})
                if isinstance(n, ast.ImportFrom):
                    imports.append({'module': '.' * n.level + (n.module or ''), 'symbols': [a.name for a in n.names], 'line': n.lineno})
                if isinstance(n, ast.Import):
                    imports.extend({'module': a.name, 'symbols': [], 'line': n.lineno} for a in n.names)
                if isinstance(n, ast.Call):
                    name = ast.unparse(n.func)
                    if re.search(r'(route|command|register|task|workflow|add_url_rule)', name, re.I):
                        entries.append({'line': n.lineno, 'symbol': name})
        except SyntaxError:
            return {'definitions': [], 'imports': [], 'entries': [], 'limitations': ['Python语法解析失败，使用原文定位']}
    elif suffix in CODE:
        clean = mask(text)
        patterns = [r'\b(?:async\s+)?function\s+(\w+)\s*\(',
                    r'\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^;{}]*?\)|\w+)\s*(?::[^=;{]+)?=>',
                    r'^\s*(?:export\s+)?(?:async\s+)?(\w+)\s*\([^;{}\n]*\)\s*(?::[^;{]+)?\{',
                    r'\bclass\s+(\w+)\b']
        seen = set()
        for pattern in patterns:
            for m in re.finditer(pattern, clean, re.M):
                if m[1] in {'if', 'for', 'while', 'switch', 'catch', 'with'}: continue
                start = clean.count('\n', 0, m.start()) + 1
                brace = body_start(clean, m)
                if brace < 0: continue
                depth = 1; end = brace + 1
                while depth and end < len(clean):
                    depth += (clean[end] == '{') - (clean[end] == '}'); end += 1
                key = (m[1], start)
                if key not in seen:
                    definitions.append({'name': m[1], 'start': start, 'end': clean.count('\n', 0, end) + 1}); seen.add(key)
        for m in re.finditer(r'(?:from\s*|require\s*\(|import\s*\()([\'\"])([^\'\"]+)\1', text):
            imports.append({'module': m[2], 'symbols': [], 'line': text.count('\n', 0, m.start()) + 1})
        for i, line in enumerate(lines, 1):
            if re.search(r'\b(?:router|app)\.(?:get|post|put|delete|patch|use)\s*\(|\b(?:register|command|addJob|processJob)\s*\(|\b(?:Query|Mutation|resolvers)\s*[:=]', line):
                entries.append({'line': i, 'symbol': line.strip()[:180]})
    else:
        return {'definitions': [], 'imports': [], 'entries': [], 'limitations': ['此语言仅使用符号与原文检索，未建立语法级引用']}
    return {'definitions': definitions, 'imports': imports, 'entries': entries,
            'limitations': ['动态导入、运行时注册和多态调用未静态证明'] if suffix != '.py' else []}


def resolve(path, module, paths):
    suffix = PurePosixPath(path).suffix
    candidates = []
    if suffix == '.py':
        if module.startswith('.'):
            level = len(module) - len(module.lstrip('.'))
            base = posixpath.dirname(path)
            for _ in range(level - 1): base = posixpath.dirname(base)
            stem = posixpath.join(base, module.lstrip('.').replace('.', '/'))
        else: stem = module.replace('.', '/')
        candidates = [stem + '.py', stem + '/__init__.py']
    elif module.startswith('.'):
        stem = posixpath.normpath(posixpath.join(posixpath.dirname(path), module))
        candidates = [stem] + [stem + ext for ext in ('.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs', '.vue')]
        candidates += [stem + '/index' + ext for ext in ('.js', '.ts', '.mjs')]
        if stem.endswith('.js'): candidates.append(stem[:-3] + '.ts')
    else:
        # Workspace package exports are resolved by Materials using package.json.
        return None
    return next((p for p in candidates if p in paths), None)


def module_key(path):
    parts = path.split('/')
    for anchor in ('modules', 'packages', 'services', 'apps'):
        if anchor in parts and parts.index(anchor) + 1 < len(parts):
            return '/'.join(parts[:parts.index(anchor) + 2])
    return '/'.join(parts[:min(2, max(1, len(parts) - 1))])


def entry_score(path):
    p = path.lower()
    return (10 * bool(re.search(r'(route|resolver|registry|register|controller|service|workflow|command|task|schema|api)', p))
            + 6 * bool(re.search(r'(^|/)(index|main|app|server)\.', p))
            + 3 * bool(re.search(r'(graphql|openapi|proto)', p)))
