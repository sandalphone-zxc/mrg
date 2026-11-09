import json,re
from pathlib import Path
from .kd_s2_architecture import module_key

def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def vue_script(text):
    """Blank non-script characters, retaining exact line positions."""
    matches=list(re.finditer(r'<script\b([^>]*)>([\s\S]*?)</script\s*>',text,re.I))
    out=['\n' if c=='\n' else ' ' for c in text]
    for m in matches:
        for i in range(m.start(2),m.end(2)):out[i]=text[i]
    return ''.join(out),bool(matches),any(re.search(r'lang\s*=\s*[\'"]tsx?[\'"]',m[1],re.I) for m in matches)


def method_summary(n):
    return {'id':n['id'],'path':n['path'],'name':n.get('NAME',''),'symbol':n.get('FULL_NAME',''),
        'start':n.get('LINE_NUMBER',1),'end':n.get('LINE_NUMBER_END',n.get('LINE_NUMBER',1)), 'module':module_key(n['path'])}
