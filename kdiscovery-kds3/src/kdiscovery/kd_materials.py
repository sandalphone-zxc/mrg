"""Repository material classification and line-preserving evidence windows."""
import re
from pathlib import PurePosixPath

SOURCE_SUFFIXES = {'.py','.pyi','.ts','.tsx','.js','.jsx','.mjs','.cjs','.c','.cpp','.cc','.cxx',
                   '.h','.hpp','.rs','.go','.java','.kt','.kts','.scala','.php','.rb','.cs',
                   '.fs','.swift','.m','.mm','.ex','.exs','.erl','.hrl','.clj','.cljs','.lua',
                   '.r','.jl','.dart','.vue','.svelte','.sh','.bash','.ps1','.sql','.scad','.qml','.ui'}
DOC_SUFFIXES = {'.md','.mdx','.rst','.txt','.adoc','.asciidoc','.html'}
SPEC_SUFFIXES = {'.json','.yaml','.yml','.toml','.xml','.proto','.graphql','.gql','.ini','.cfg'}


def material_kind(path):
    p = PurePosixPath(path.lower()); parts = p.parts; name = p.name
    if any(s in parts for s in ('node_modules','vendor','.git','dist','build','__pycache__')): return None
    if p.suffix not in SOURCE_SUFFIXES | DOC_SUFFIXES | SPEC_SUFFIXES | {'.ipynb'} and name not in ('dockerfile','makefile','gemfile','rakefile','procfile','license'): return None
    if path.lower().startswith('.github/workflows/'): return 'engineering'
    if any(s in parts for s in ('test','tests','spec','specs','e2e','integration')) or re.search(r'(^test_|[._](test|spec)\.)',name): return 'test'
    if p.suffix == '.ipynb' or any(s in parts for s in ('examples','example','tutorial','tutorials')): return 'example'
    if p.suffix in ('.proto','.graphql','.gql') or any(s in name for s in ('openapi','swagger','route','registry','register','cli')): return 'interface'
    if p.suffix in DOC_SUFFIXES: return 'document'
    if p.suffix in SPEC_SUFFIXES or name in ('dockerfile','makefile','gemfile','procfile'): return 'runtime'
    return 'implementation'


def visible_line(source, line):
    if not source or type(line) is not int or line < 1: return False
    ranges = source.get('visible_ranges')
    return any(a <= line <= b for a,b in ranges) if ranges is not None else line <= source.get('shown_lines',0)
