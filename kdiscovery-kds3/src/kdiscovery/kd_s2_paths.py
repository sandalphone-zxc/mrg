"""Repository-owned KD-S-2 directories, independent of mining semantics."""
import json
import os
import re
import stat
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager

_location = ContextVar('kd_s2_output_location', default=None)

@contextmanager
def output_location(folder, repo, commit, job_id):
    token=_location.set((Path(folder),repo,commit,job_id))
    try:yield
    finally:_location.reset(token)


def _native(path):
    value=str(path)
    return Path('\\\\?\\'+value) if os.name=='nt' and not value.startswith('\\\\?\\') else path


def safe_path(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    if not path.is_relative_to(root):
        raise ValueError('知识路径越界')
    for item in (root, *reversed(path.relative_to(root).parents)):
        candidate = item if item == root else root / item
        candidate=_native(candidate)
        if candidate.is_symlink() or (candidate.exists() and getattr(candidate.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('知识路径含链接或重解析点')
    native=_native(path)
    if native.is_symlink() or (native.exists() and getattr(native.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError('知识路径含链接或重解析点')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('知识路径越界')
    return path


def project_folder(workspace, repo, claim=False):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo) or any(v in ('.', '..') for v in repo.split('/')):
        raise ValueError('无效 GitHub 仓库标识')
    name = repo.split('/')[1]
    if name.endswith('.') or name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
        raise ValueError('项目名称不能用作本地目录')
    root = Path(workspace) / 'mrg-project/knowledge'
    matches = [p for p in root.iterdir() if p.name.casefold() == name.casefold()] if root.exists() else []
    if len(matches) > 1: raise ValueError('存在大小写冲突的项目目录')
    folder = safe_path(root, matches[0] if matches else root / name)
    marker = folder / '.repository.json'
    if marker.exists():
        owner = json.loads(safe_path(root, marker).read_text(encoding='utf-8'))['repo']
        if owner.casefold() != repo.casefold(): raise ValueError(f'项目名称冲突：{name} 已属于 {owner}，不能写入 {repo}')
    elif folder.exists() and any(folder.iterdir()):
        manifests = list(folder.glob('KD-S-2/*/*/manifest.json'))
        if (folder/'manifest.json').is_file():manifests.append(folder/'manifest.json')
        if not manifests or any(json.loads(safe_path(root, p).read_text(encoding='utf-8')).get('repo','').casefold() != repo.casefold() for p in manifests):
            raise ValueError(f'无法确认项目目录 {name} 的仓库归属，禁止混放')
    if claim:
        folder.mkdir(parents=True, exist_ok=True)
        try:
            with marker.open('x', encoding='utf-8') as f: json.dump({'repo':repo}, f, ensure_ascii=False)
        except FileExistsError:
            if json.loads(marker.read_text(encoding='utf-8'))['repo'].casefold()!=repo.casefold():
                raise ValueError(f'项目名称冲突：{name}')
    return folder


def run_folder(workspace, repo, commit, job_id, claim=False):
    if not re.fullmatch(r'[a-fA-F0-9]{40}', commit) or not re.fullmatch(r'[\w-]+', job_id):
        raise ValueError('无效源码版本或运行ID')
    location=_location.get()
    if location:
        if location[1:]!=(repo,commit,job_id):raise ValueError('暂存任务身份不匹配')
        return safe_path(Path(workspace)/'research',location[0])
    root = Path(workspace) / 'mrg-project/knowledge'
    project = project_folder(workspace, repo, claim)
    manifest = project / 'manifest.json'
    if manifest.is_file():
        saved = json.loads(safe_path(root, manifest).read_text(encoding='utf-8'))
        if saved.get('run_id') == job_id and saved.get('commit') == commit:
            return project
    return safe_path(root, project / 'KD-S-2' / commit / job_id)


def check_maintenance(workspace):
    if (Path(workspace) / 'mrg-project/data/knowledge-maintenance.json').exists():
        raise ValueError('知识目录正在整理，请稍后重试')
