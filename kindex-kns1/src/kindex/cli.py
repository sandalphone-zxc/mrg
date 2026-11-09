import argparse,json,os,sys
from pathlib import Path
from . import KIndex,HierarchicalIndex,SQLiteStore,KeywordOnlyProvider

def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf8')
    p=argparse.ArgumentParser(description='KN-S-1 knowledge snapshot index')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('strategies')
    build=sub.add_parser('build');build.add_argument('input');build.add_argument('--vectors',action='store_true')
    search=sub.add_parser('search');search.add_argument('snapshot');search.add_argument('query');search.add_argument('--vectors',action='store_true')
    search.add_argument('--limit',type=int,default=12);search.add_argument('--include-units',action='store_true')
    rel=sub.add_parser('relatives');rel.add_argument('snapshot');rel.add_argument('node');rel.add_argument('--direction',choices=['parents','children'],default='parents')
    for c in (build,search,rel):c.add_argument('--db',required=True)
    args=p.parse_args(argv)
    try:
        if args.command=='strategies':result=KIndex.describe()
        else:
            provider=KeywordOnlyProvider()
            if getattr(args,'vectors',False):
                from .providers import OpenAIEmbeddingProvider
                provider=OpenAIEmbeddingProvider(os.environ.get('KINDEX_EMBEDDING_ENDPOINT',''),os.environ.get('KINDEX_EMBEDDING_MODEL',''),os.environ.get('KINDEX_API_KEY',''))
            index=HierarchicalIndex(SQLiteStore(args.db),provider)
            if args.command=='build':result=index.build(json.loads(Path(args.input).read_text(encoding='utf-8-sig')))
            elif args.command=='search':result=index.search(args.snapshot,args.query,limit=args.limit,include_units=args.include_units,use_vectors=args.vectors)
            else:result=index.relatives(args.snapshot,args.node,args.direction)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,RuntimeError,LookupError,OSError) as exc:
        print(str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
