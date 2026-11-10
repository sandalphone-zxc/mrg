import { MarkerType, type Edge, type Node } from '@xyflow/react';

export const kinds = ['输入', '计算', '推理', '结论'] as const;
export const relations = ['提供数据', '支持判断', '反证', '进入下一步'] as const;
export type Kind = typeof kinds[number];
export type Relation = typeof relations[number];
export type Evidence = '原文支持' | '据原文整理' | '教学示例' | '本地编辑';
export type NodeData = {
  title: string; kind: Kind; status: Evidence; detail: string;
  inputs: string; check: string; example?: string; sources?: number[];
};
export type EdgeData = { relation: Relation; note: string };
export type MapNode = Node<NodeData, 'method'>;
export type MapEdge = Edge<EdgeData>;
export type Graph = { nodes: MapNode[]; edges: MapEdge[] };
export type Method = Graph & {
  id: string; name: string; fullName: string; title: string; summary: string;
  sources: { title: string; url: string }[];
  audit: { status: Evidence; text: string; sources: number[] }[];
};

export function node(id: string, x: number, y: number, kind: Kind, title: string,
  status: Evidence, detail: string, inputs: string, check: string, sources: number[] = [], example?: string): MapNode {
  return { id, type: 'method', position: { x: x * 230, y: y * 124 },
    data: { title, kind, status, detail, inputs, check, sources, example } };
}

export function edge(source: string, target: string, relation: Relation, note: string, id = source + '-' + target): MapEdge {
  return { id, source, target, type: 'smoothstep', label: relation, data: { relation, note },
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
    className: relation === '反证' ? 'counter-edge' : undefined };
}
