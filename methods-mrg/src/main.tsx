import { useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import {
  applyNodeChanges, Background, BackgroundVariant, Controls,
  Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, useReactFlow,
  type Connection, type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './style.css';
import { methods } from './methods';
import { edge, kinds, node, relations, type Graph, type MapEdge, type MapNode, type Method, type NodeData } from './model';

const kindIndex = (kind: NodeData['kind']) => kinds.indexOf(kind);
const fitOptions = { padding: 0.14, maxZoom: 1 };
type Selection = { type: 'node' | 'edge'; id: string };

function MethodNode({ data }: NodeProps<MapNode>) {
  return (
    <div className={'map-node kind-' + kindIndex(data.kind)}>
      <Handle type="target" position={Position.Left} aria-label="连接输入" />
      <span className="node-kind"><i />{data.kind}</span>
      <strong>{data.title}</strong>
      <Handle type="source" position={Position.Right} aria-label="连接输出" />
    </div>
  );
}

const nodeTypes = { method: MethodNode };

function loadGraph(method: Method): { graph: Graph; edited: boolean; warning: string } {
  try {
    const saved = localStorage.getItem('investment-atlas:v1:' + method.id);
    if (saved) {
      const graph = JSON.parse(saved) as Graph;
      if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) throw new Error();
      return { graph, edited: true, warning: '' };
    }
  } catch {
    return { graph: method, edited: false, warning: '本地图谱读取失败，已显示核验版。' };
  }
  return { graph: method, edited: false, warning: '' };
}

function SourceLinks({ method, ids }: { method: Method; ids: number[] }) {
  return <ul className="sources">{ids.map(id => (
    <li key={id}><a href={method.sources[id].url} target="_blank" rel="noreferrer">{method.sources[id].title} ↗</a></li>
  ))}</ul>;
}

function Overview({ method }: { method: Method }) {
  return <>
    <div className="inspector-title"><h2>原文核验</h2><p>逐条区分原文观点、导图整理和计算示例。</p></div>
    <div className="audit-list">{method.audit.map(item => (
      <section key={item.status} className="audit-item">
        <span className="evidence">{item.status}</span>
        <p>{item.text}</p>
        <SourceLinks method={method} ids={item.sources} />
      </section>
    ))}</div>
  </>;
}

function NodeDetails({ data, method }: { data: NodeData; method: Method }) {
  return <>
    <div className="inspector-title">
      <span className={'kind-pill kind-' + kindIndex(data.kind)}><i />{data.kind}</span>
      <h2>{data.title}</h2>
      <span className="evidence">{data.status}</span>
    </div>
    <dl className="details">
      <dt>{data.kind === '计算' ? '计算公式' : '内容'}</dt><dd>{data.detail || '待填写'}</dd>
      <dt>{data.kind === '推理' ? '推理所需证据' : '所需输入'}</dt><dd>{data.inputs || '待填写'}</dd>
      <dt>{data.kind === '推理' ? '反证与证据不足时的处理' : '口径与检查'}</dt><dd>{data.check || '待填写'}</dd>
      {data.example && <><dt>虚构样例</dt><dd className="example">{data.example}</dd></>}
    </dl>
    {data.sources && data.sources.length > 0 && <SourceLinks method={method} ids={data.sources} />}
  </>;
}

function NodeEditor({ data, save, remove }: { data: NodeData; save: (data: NodeData) => void; remove: () => void }) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const title = String(fields.get('title')).trim();
    if (!title) return;
    save({
      ...data, title, status: '本地编辑', kind: fields.get('kind') as NodeData['kind'],
      detail: String(fields.get('detail')), inputs: String(fields.get('inputs')),
      check: String(fields.get('check')), example: String(fields.get('example')),
    });
  }
  return <form className="edit-form" onSubmit={submit}>
    <label>节点名称<input name="title" defaultValue={data.title} required maxLength={48} /></label>
    <label>类型<select name="kind" defaultValue={data.kind}>{kinds.map(kind => <option key={kind}>{kind}</option>)}</select></label>
    <label>说明或公式<textarea name="detail" defaultValue={data.detail} /></label>
    <label>所需输入或证据<textarea name="inputs" defaultValue={data.inputs} /></label>
    <label>口径、反证与检查<textarea name="check" defaultValue={data.check} /></label>
    <label>虚构样例<textarea name="example" defaultValue={data.example} /></label>
    <div className="form-actions"><button className="primary">保存节点</button><button type="button" className="danger" onClick={remove}>删除节点</button></div>
  </form>;
}

function EdgeEditor({ current, nodes, save, remove }: {
  current: MapEdge; nodes: MapNode[]; save: (item: MapEdge) => void; remove: () => void;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    save(edge(String(fields.get('source')), String(fields.get('target')),
      fields.get('relation') as NonNullable<MapEdge['data']>['relation'], String(fields.get('note')), current.id));
  }
  return <form className="edit-form" onSubmit={submit}>
    <label>起点<select name="source" defaultValue={current.source}>{nodes.map(item => <option key={item.id} value={item.id}>{item.data.title}</option>)}</select></label>
    <label>终点<select name="target" defaultValue={current.target}>{nodes.map(item => <option key={item.id} value={item.id}>{item.data.title}</option>)}</select></label>
    <label>关系标签<select name="relation" defaultValue={current.data?.relation}>{relations.map(relation => <option key={relation}>{relation}</option>)}</select></label>
    <label>连线说明<textarea name="note" defaultValue={current.data?.note} /></label>
    <div className="form-actions"><button className="primary">保存连线</button><button type="button" className="danger" onClick={remove}>删除连线</button></div>
  </form>;
}

function Workspace({ method }: { method: Method }) {
  const [initial] = useState(() => loadGraph(method));
  const [graph, setGraph] = useState(initial.graph);
  const [edited, setEdited] = useState(initial.edited);
  const [warning, setWarning] = useState(initial.warning);
  const [feedback, setFeedback] = useState('');
  const [editing, setEditing] = useState(false);
  const [selection, setSelection] = useState<Selection>();
  const { fitView, screenToFlowPosition } = useReactFlow<MapNode, MapEdge>();
  const activeNode = selection?.type === 'node' ? graph.nodes.find(item => item.id === selection.id) : undefined;
  const activeEdge = selection?.type === 'edge' ? graph.edges.find(item => item.id === selection.id) : undefined;
  const label = (id: string) => graph.nodes.find(item => item.id === id)?.data.title || id;

  useEffect(() => {
    if (!edited || graph.nodes.some(item => item.dragging)) return;
    try {
      const nodes = graph.nodes.map(({ id, type, position, data }) => ({ id, type, position, data }));
      const edges = graph.edges.map(({ source, target, data, id }) =>
        edge(source, target, data?.relation ?? '进入下一步', data?.note ?? '', id));
      localStorage.setItem('investment-atlas:v1:' + method.id, JSON.stringify({ nodes, edges }));
      setWarning('');
    } catch {
      setWarning('浏览器无法保存改动，刷新可能丢失。');
    }
  }, [edited, graph, method.id]);

  function select(type: Selection['type'], id: string) {
    setFeedback('');
    setSelection({ type, id });
  }

  function clearSelection() {
    setFeedback('');
    setSelection(undefined);
  }

  function addNode() {
    const bounds = document.querySelector('.canvas')?.getBoundingClientRect();
    const position = bounds ? screenToFlowPosition({ x: bounds.left + bounds.width / 2 - 90, y: bounds.top + 95 }) : { x: 0, y: 0 };
    const item = { ...node(crypto.randomUUID(), 0, 0, '输入', '新节点', '本地编辑', '', '', ''), position };
    setGraph(previous => ({ ...previous, nodes: [...previous.nodes, item] }));
    setEdited(true);
    select('node', item.id);
  }

  function saveEdge(item: MapEdge, message = '已保存连线') {
    const ids = new Set(graph.nodes.map(current => current.id));
    if (!ids.has(item.source) || !ids.has(item.target) || item.source === item.target) {
      setFeedback('请选择两个不同且存在的节点。');
      return;
    }
    if (graph.edges.some(current => current.id !== item.id && current.source === item.source && current.target === item.target)) {
      setFeedback('这两个节点之间已有同向连线。');
      return;
    }
    setGraph(previous => ({ ...previous, edges: previous.edges.some(current => current.id === item.id)
      ? previous.edges.map(current => current.id === item.id ? item : current)
      : [...previous.edges, item] }));
    setEdited(true);
    setSelection({ type: 'edge', id: item.id });
    setFeedback(message);
  }

  function connect(connection: Connection) {
    saveEdge(edge(connection.source, connection.target, '进入下一步', '', crypto.randomUUID()), '已新增连线');
  }

  function reconnect(current: MapEdge, connection: Connection) {
    saveEdge(edge(connection.source, connection.target, current.data?.relation ?? '进入下一步', current.data?.note ?? '', current.id));
  }

  function removeSelected() {
    if (!selection) return;
    const { id, type } = selection;
    setGraph(previous => ({
      nodes: type === 'node' ? previous.nodes.filter(item => item.id !== id) : previous.nodes,
      edges: previous.edges.filter(item => type === 'node' ? item.source !== id && item.target !== id : item.id !== id),
    }));
    setEdited(true);
    setSelection(undefined);
    setFeedback(type === 'node' ? '已删除节点及关联连线' : '已删除连线');
  }

  function restore() {
    if (!window.confirm('恢复当前图的核验版并清除这张图的本地改动？')) return;
    try {
      localStorage.removeItem('investment-atlas:v1:' + method.id);
    } catch {
      setWarning('浏览器无法清除保存的改动。');
      return;
    }
    setGraph(method);
    setEdited(false);
    setWarning('');
    setSelection(undefined);
    setFeedback('已恢复当前图的核验版');
    void fitView({ ...fitOptions, duration: 200 });
  }

  return <main className="workspace">
    <header className="method-header">
      <div>
        <div className="method-meta">{method.fullName}<span className={edited ? 'version edited' : 'version'}>{edited ? '本地编辑版' : '核验版'}</span></div>
        <h1>{method.title}</h1>
        <p>{method.summary}</p>
      </div>
      <div className="header-actions">
        {edited && <button className="quiet" onClick={restore}>恢复核验版</button>}
        <button className={editing ? 'secondary' : 'primary'} aria-pressed={editing} onClick={() => { setEditing(!editing); setFeedback(''); }}>
          {editing ? '退出编辑' : '编辑图谱'}
        </button>
      </div>
    </header>
    <div className="work-body">
      <section className="graph-panel" aria-label={method.fullName + '的投资方法图'}>
        <div className="toolbar">
          <div className="legend" aria-label="节点类型">{kinds.map((kind, index) => (
            <span className={'kind-pill kind-' + index} key={kind}><i />{kind}</span>
          ))}</div>
          {editing ? <button className="secondary compact" onClick={addNode}>＋ 新增节点</button>
            : <button className="quiet compact" onClick={() => { void fitView({ ...fitOptions, duration: 200 }); }}>适应画布</button>}
        </div>
        <div className="canvas">
          <ReactFlow<MapNode, MapEdge>
            nodes={graph.nodes.map(item => ({ ...item, selected: item.id === activeNode?.id }))}
            edges={graph.edges.map(item => ({ ...item, selected: item.id === activeEdge?.id }))}
            nodeTypes={nodeTypes}
            fitView fitViewOptions={fitOptions} minZoom={0.15} maxZoom={2}
            nodesConnectable={editing} edgesReconnectable={editing} deleteKeyCode={null}
            onNodesChange={changes => setGraph(previous => ({ ...previous, nodes: applyNodeChanges(changes, previous.nodes) }))}
            onEdgeClick={(_, item) => select('edge', item.id)}
            onNodeClick={(_, item) => select('node', item.id)}
            onPaneClick={clearSelection}
            onNodeDragStop={(event, item) => {
              setGraph(previous => ({ ...previous, nodes: previous.nodes.map(current =>
                current.id === item.id ? { ...current, position: item.position, dragging: false } : current) }));
              setEdited(true);
              if (event.type === 'mouseup') setFeedback('');
            }}
            onEdgeDoubleClick={(_, item) => { setEditing(true); select('edge', item.id); }}
            onConnect={connect} onReconnect={reconnect}
            proOptions={{ hideAttribution: true }}
            ariaLabelConfig={{
              'controls.ariaLabel': '画布控件', 'controls.zoomIn.ariaLabel': '放大',
              'controls.zoomOut.ariaLabel': '缩小', 'controls.fitView.ariaLabel': '适应画布',
            }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#dce3ea" />
            <Controls showInteractive={false} fitViewOptions={fitOptions} />
            <MiniMap<MapNode> pannable zoomable ariaLabel="导图缩略图" nodeColor={item => ['#72a4de', '#d6a450', '#ac96d8', '#70b49c'][kindIndex(item.data.kind)]} />
          </ReactFlow>
        </div>
        <footer className="canvas-footer">
          <span>{graph.nodes.length} 个节点 · {graph.edges.length} 条连线</span>
          <span>{editing ? '拖动节点连接点可新增连线' : '滚轮缩放 · 拖动画布平移 · 点击查看详情'}</span>
        </footer>
      </section>
      <aside className="inspector" aria-label="详情与原文核验">
        <div className="inspector-bar">
          <span>{activeNode ? '节点详情' : activeEdge ? '连线详情' : '研究记录'}</span>
          {(activeNode || activeEdge) && <button className="quiet compact" onClick={clearSelection}>返回核验</button>}
        </div>
        <div className="inspector-content">
          {(feedback || warning) && <p className="feedback" role="status">{warning || feedback}</p>}
          {activeNode ? <>
            <NodeDetails data={activeNode.data} method={method} />
            {editing && <NodeEditor key={activeNode.id} data={activeNode.data} remove={removeSelected} save={data => {
              setGraph(previous => ({ ...previous, nodes: previous.nodes.map(item => item.id === activeNode.id ? { ...item, data } : item) }));
              setEdited(true);
              setFeedback('已保存节点');
            }} />}
          </> : activeEdge ? <>
            <div className="inspector-title"><h2>{activeEdge.data?.relation}</h2><p>{label(activeEdge.source)} → {label(activeEdge.target)}</p></div>
            <dl className="details"><dt>连线说明</dt><dd>{activeEdge.data?.note || '待填写'}</dd></dl>
            {editing && <EdgeEditor key={activeEdge.id + ':' + activeEdge.source + ':' + activeEdge.target}
              current={activeEdge} nodes={graph.nodes} save={saveEdge} remove={removeSelected} />}
          </> : <Overview method={method} />}
        </div>
      </aside>
    </div>
  </main>;
}

function App() {
  const [method, setMethod] = useState(() => methods.find(item => '#' + item.id === location.hash) ?? methods[0]);
  useEffect(() => {
    const followHash = () => setMethod(methods.find(item => '#' + item.id === location.hash) ?? methods[0]);
    window.addEventListener('hashchange', followHash);
    return () => window.removeEventListener('hashchange', followHash);
  }, []);
  return <div className="app">
    <nav className="sidebar" aria-label="投资人列表">
      <div className="brand"><div className="brand-mark" aria-hidden="true">⌘</div><div><strong>投资方法图谱</strong><small>投资研究工具</small></div></div>
      <div className="nav-heading"><span>投资人</span><span>05</span></div>
      {methods.map((item, index) => (
        <a key={item.id} href={'#' + item.id} className={item.id === method.id ? 'nav-item current' : 'nav-item'}
          aria-current={item.id === method.id ? 'page' : undefined}>
          <span className="nav-index">{String(index + 1).padStart(2, '0')}</span>
          <span><strong>{item.name}</strong><small>{item.title}</small></span>
        </a>
      ))}
      <div className="sidebar-foot">图谱改动保存在当前浏览器。<br />公式示例使用虚构数据。</div>
    </nav>
    <ReactFlowProvider key={method.id}><Workspace method={method} /></ReactFlowProvider>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
