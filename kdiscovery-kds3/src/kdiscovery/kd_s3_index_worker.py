"""Isolated native grammar process. Source is read, never imported or executed."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kdiscovery.kd_s3_index import parse_file
from kdiscovery.kd_s2_sources import atomic
from kdiscovery.kd_s2_format import digest

def main(path):
    request=json.loads(Path(path).read_text(encoding='utf8'))
    for row in request['rows']:
        atomic(Path(request['progress']),{'path':row['path']})
        try:
            blob=Path(row['source']).read_bytes()
            if digest(blob)!=row['sha256']:raise ValueError('解析输入内容哈希变化')
            text=blob.decode('utf-8-sig')
            if '\0' in text:raise ValueError('非文本原文')
            definitions,calls,imports,limits=parse_file(Path(request['workspace']),row['path'],text)
            result={'path':row['path'],'definitions':definitions,'calls':calls,'imports':imports,'limits':limits}
        except Exception as exc:
            result={'path':row['path'],'definitions':[],'calls':[],'imports':[],'limits':[type(exc).__name__+': '+str(exc)[:350]]}
        atomic(Path(row['target']),result)

if __name__=='__main__':main(sys.argv[1])
