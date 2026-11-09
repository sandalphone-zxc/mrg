"""Installed, pinned parser identity; no host workspace or bundled executables."""
from importlib import metadata
from .kd_s2_format import digest

VERSIONS = {
    'tree-sitter': '0.25.2', 'tree-sitter-bash': '0.25.1',
    'tree-sitter-cpp': '0.23.4', 'tree-sitter-java': '0.23.5',
    'tree-sitter-javascript': '0.25.0', 'tree-sitter-php': '0.25.1',
    'tree-sitter-python': '0.25.0', 'tree-sitter-scala': '0.26.4',
    'tree-sitter-typescript': '0.23.2',
}

def identity():
    binaries = {}
    for name, expected in VERSIONS.items():
        dist = metadata.distribution(name)
        if dist.version != expected:
            raise ValueError(f'{name} requires {expected}, found {dist.version}')
        found = False
        for item in dist.files or []:
            if str(item).endswith(('.pyd', '.so', '.dylib')):
                binaries[name+'/'+str(item)] = digest(dist.locate_file(item).read_bytes())
                found = True
        if not found:
            raise ValueError(f'Missing parser binary: {name}')
    return {'name': 'tree-sitter-symbol-index', 'versions': dict(VERSIONS), 'binaries': binaries}
