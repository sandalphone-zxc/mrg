"""Fail fast on invalid ownership; do not infer business dependency edges."""
def validate_snapshot(snapshot):
    if not isinstance(snapshot,dict) or not isinstance(snapshot.get('id'),str) or not snapshot['id']:
        raise ValueError('snapshot.id must be a nonempty string')
    for key in ('projects','entities','rows'):
        if not isinstance(snapshot.get(key),dict):raise ValueError(f'snapshot.{key} must be an object')
    projects,entities,rows=snapshot['projects'],snapshot['entities'],snapshot['rows']
    owners={};parents={}
    for pid,project in projects.items():
        try:roots=project['mns']['SOP_refs']
        except (KeyError,TypeError):raise ValueError(f'{pid}: missing mns.SOP_refs') from None
        if not isinstance(roots,list):raise ValueError('SOP_refs must be a list')
        pending=[(sid,None) for sid in roots]
        while pending:
            sid,parent=pending.pop()
            if not isinstance(sid,str) or sid not in entities:raise ValueError('Dangling SOP reference')
            if sid in owners:raise ValueError('SOP cycle, duplicate ownership or multiple parents')
            sop=entities[sid]
            if not isinstance(sop,dict) or any(not isinstance(sop.get(k),str) for k in ('name','goal')):
                raise ValueError('SOP must have string name and goal')
            owners[sid]=pid;parents[sid]=parent
            children=sop.get('sub_sop_refs',[])
            if not isinstance(children,list):raise ValueError('sub_sop_refs must be a list')
            pending.extend((child,sid) for child in children)
    if any(sid not in owners for sid in rows):raise ValueError('Feature row is not owned by a project SOP')
    trees=snapshot.get('trees',{})
    if not isinstance(trees,dict):raise ValueError('trees must be an object')
    for pid,tree in trees.items():
        if pid not in projects:raise ValueError('Unit tree has unknown project')
        if not isinstance(tree,dict) or not isinstance(tree.get('nodes',[]),list):raise ValueError('Invalid unit tree')
        for unit in tree.get('nodes',[]):
            if not isinstance(unit,dict) or 'type' not in unit:raise ValueError('Invalid tree node')
            if unit['type']!='unit':continue
            for key in ('id','parent','name','purpose'):
                if not isinstance(unit.get(key),str):raise ValueError(f'Unit missing {key}')
            if unit['id'] in owners:raise ValueError('Duplicate unit ID')
            if 'commit' not in tree or not isinstance(unit.get('confidence'),(int,float)):raise ValueError('Unit requires commit and confidence')
            owners[unit['id']]=pid;parents[unit['id']]=unit['parent']
    for sid,parent in parents.items():
        seen={sid}
        while parent is not None:
            if parent not in owners or owners[parent]!=owners[sid]:raise ValueError('Dangling or cross-project parent')
            if parent in seen:raise ValueError('Hierarchy cycle')
            seen.add(parent);parent=parents[parent]
    return snapshot
