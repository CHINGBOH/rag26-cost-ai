/**
 * 递归状态管理
 * 管理可无限下钻的节点树
 */

import { create } from 'zustand';
import {
  RecursiveNode,
  RecursiveViewState,
  RecursiveBranch,
  RecursiveUIEvent
} from '@rag/shared';

// 生成唯一ID
const generateId = () => crypto.randomUUID().slice(0, 13);

// 创建示例递归节点（用于测试）
const createSampleNode = (
  type: RecursiveNode['type'],
  content: string,
  depth: number,
  path: string[],
  parent?: string
): RecursiveNode => ({
  id: generateId(),
  type,
  content,
  metadata: {
    timestamp: Date.now(),
    author: 'system',
    tags: []
  },
  children: [],
  parent,
  recursionMeta: {
    depth,
    path: [...path],
    informationGain: Math.random() * 0.5,
    confidence: 0.5 + Math.random() * 0.5
  },
  uiState: {
    expanded: false,
    selected: false,
    userModified: false
  }
});

// 递归构建示例树
const buildSampleTree = (): RecursiveNode => {
  const root = createSampleNode(
    'answer',
    '递归RAG系统通过专家判断动态控制检索深度，实现精准问答。',
    0,
    ['root']
  );

  // 第一层子节点
  const claim1 = createSampleNode(
    'claim',
    '专家判断是核心机制，负责评估答案质量并决定下一步行动。',
    1,
    ['root', 'claim1'],
    root.id
  );
  
  const claim2 = createSampleNode(
    'claim',
    '动态边界检测避免了固定深度带来的资源浪费和信息不足。',
    1,
    ['root', 'claim2'],
    root.id
  );

  // 第二层：证据
  const evidence1 = createSampleNode(
    'evidence',
    '实验数据显示，动态边界比固定深度节省40%的API调用，同时提高15%的准确率。',
    2,
    ['root', 'claim1', 'ev1'],
    claim1.id
  );

  const evidence2 = createSampleNode(
    'source',
    '来源：《Adaptive Retrieval Systems》2024年论文，第3节。',
    2,
    ['root', 'claim1', 'src1'],
    claim1.id
  );

  // 第三层：矛盾
  const contradiction = createSampleNode(
    'contradiction',
    '但是，该论文也指出动态边界在某些情况下会过度思考。',
    3,
    ['root', 'claim1', 'ev1', 'contradict'],
    evidence1.id
  );

  evidence1.children = [contradiction];
  claim1.children = [evidence1, evidence2];
  root.children = [claim1, claim2];

  // 更新路径中的ID
  claim1.recursionMeta.path = [root.id, claim1.id];
  claim2.recursionMeta.path = [root.id, claim2.id];
  evidence1.recursionMeta.path = [root.id, claim1.id, evidence1.id];
  evidence2.recursionMeta.path = [root.id, claim1.id, evidence2.id];
  contradiction.recursionMeta.path = [root.id, claim1.id, evidence1.id, contradiction.id];

  return root;
};

interface RecursiveStore {
  // 节点树（按ID索引）
  nodes: Map<string, RecursiveNode>;
  
  // 当前视野状态
  viewState: RecursiveViewState;
  
  // 事件历史
  eventHistory: RecursiveUIEvent[];
  
  // 当前会话的根节点
  rootNode?: RecursiveNode;
  
  // 操作
  initialize: (rootNode?: RecursiveNode) => void;
  drillDown: (nodeId: string) => void;
  climbUp: () => void;
  jumpTo: (path: string[]) => void;
  createBranch: (fromNodeId: string, name: string) => RecursiveBranch;
  annotate: (nodeId: string, annotation: string) => void;
  toggleExpand: (nodeId: string) => void;
  addChild: (parentId: string, child: RecursiveNode) => void;
  updateNode: (nodeId: string, updates: Partial<RecursiveNode>) => void;
  
  // 获取当前焦点节点
  getFocusNode: () => RecursiveNode | undefined;
  
  // 获取节点
  getNode: (id: string) => RecursiveNode | undefined;
}

export const useRecursiveStore = create<RecursiveStore>((set, get) => ({
  nodes: new Map(),
  viewState: {
    focusNodeId: '',
    history: [],
    branches: new Map(),
    globalMeta: {
      maxDepthReached: 0,
      totalNodes: 0,
      userBranches: 0,
      lastUpdate: Date.now()
    }
  },
  eventHistory: [],
  rootNode: undefined,

  // 初始化
  initialize: (rootNode) => {
    const root = rootNode || buildSampleTree();
    const nodes = new Map<string, RecursiveNode>();
    
    // 递归遍历所有节点加入map
    const traverse = (node: RecursiveNode) => {
      nodes.set(node.id, node);
      node.children.forEach(traverse);
    };
    traverse(root);

    set({
      nodes,
      rootNode: root,
      viewState: {
        focusNodeId: root.id,
        history: [],
        branches: new Map(),
        globalMeta: {
          maxDepthReached: Math.max(...Array.from(nodes.values()).map(n => n.recursionMeta.depth)),
          totalNodes: nodes.size,
          userBranches: 0,
          lastUpdate: Date.now()
        }
      }
    });
  },

  // 下钻
  drillDown: (nodeId) => {
    const { viewState, nodes, eventHistory } = get();
    const node = nodes.get(nodeId);
    if (!node) return;

    const newHistory = [...viewState.history, viewState.focusNodeId];
    
    set({
      viewState: {
        ...viewState,
        focusNodeId: nodeId,
        history: newHistory
      },
      eventHistory: [...eventHistory, {
        type: 'drill_down',
        from: nodes.get(viewState.focusNodeId)!,
        to: node
      }]
    });
  },

  // 上爬
  climbUp: () => {
    const { viewState, nodes, eventHistory } = get();
    if (viewState.history.length === 0) return;

    const parentId = viewState.history[viewState.history.length - 1];
    const parent = nodes.get(parentId);
    if (!parent) return;

    set({
      viewState: {
        ...viewState,
        focusNodeId: parentId,
        history: viewState.history.slice(0, -1)
      },
      eventHistory: [...eventHistory, {
        type: 'climb_up',
        from: nodes.get(viewState.focusNodeId)!,
        to: parent
      }]
    });
  },

  // 跳转到指定路径
  jumpTo: (path) => {
    if (path.length === 0) return;
    const targetId = path[path.length - 1];
    
    set(state => ({
      viewState: {
        ...state.viewState,
        focusNodeId: targetId,
        history: path.slice(0, -1)
      }
    }));
  },

  // 创建分支
  createBranch: (fromNodeId, name) => {
    const { viewState, nodes, rootNode } = get();
    const fromNode = nodes.get(fromNodeId);
    if (!fromNode || !rootNode) throw new Error('Node not found');

    const branchId = generateId();
    
    // 创建分支的根节点（复制原节点但清空历史）
    const branchRoot: RecursiveNode = {
      ...fromNode,
      id: generateId(),
      uiState: {
        ...fromNode.uiState,
        branchFrom: fromNodeId,
        userModified: true
      },
      recursionMeta: {
        ...fromNode.recursionMeta,
        path: ['branch', branchId, fromNode.id]
      }
    };

    const branch: RecursiveBranch = {
      id: branchId,
      name,
      forkedFrom: fromNodeId,
      forkedAt: Date.now(),
      rootNode: branchRoot,
      status: 'active'
    };

    const newBranches = new Map(viewState.branches);
    newBranches.set(branchId, branch);

    set({
      viewState: {
        ...viewState,
        branches: newBranches,
        globalMeta: {
          ...viewState.globalMeta,
          userBranches: viewState.globalMeta.userBranches + 1
        }
      }
    });

    return branch;
  },

  // 标注
  annotate: (nodeId, annotation) => {
    const { nodes } = get();
    const node = nodes.get(nodeId);
    if (!node) return;

    const updatedNode: RecursiveNode = {
      ...node,
      metadata: {
        ...node.metadata,
        tags: [...node.metadata.tags, `annotation:${annotation}`]
      },
      uiState: {
        ...node.uiState,
        userModified: true
      }
    };

    const newNodes = new Map(nodes);
    newNodes.set(nodeId, updatedNode);

    set({ nodes: newNodes });
  },

  // 展开/折叠
  toggleExpand: (nodeId) => {
    const { nodes } = get();
    const node = nodes.get(nodeId);
    if (!node) return;

    const updatedNode: RecursiveNode = {
      ...node,
      uiState: {
        ...node.uiState,
        expanded: !node.uiState.expanded
      }
    };

    const newNodes = new Map(nodes);
    newNodes.set(nodeId, updatedNode);

    set({ nodes: newNodes });
  },

  // 添加子节点
  addChild: (parentId, child) => {
    const { nodes, viewState } = get();
    const parent = nodes.get(parentId);
    if (!parent) return;

    // 更新父节点
    const updatedParent: RecursiveNode = {
      ...parent,
      children: [...parent.children, child]
    };

    // 添加子节点到map
    const newNodes = new Map(nodes);
    newNodes.set(parentId, updatedParent);
    newNodes.set(child.id, {
      ...child,
      parent: parentId,
      recursionMeta: {
        ...child.recursionMeta,
        depth: parent.recursionMeta.depth + 1,
        path: [...parent.recursionMeta.path, child.id]
      }
    });

    // 更新全局元信息
    const maxDepth = Math.max(
      viewState.globalMeta.maxDepthReached,
      parent.recursionMeta.depth + 1
    );

    set({
      nodes: newNodes,
      viewState: {
        ...viewState,
        globalMeta: {
          ...viewState.globalMeta,
          maxDepthReached: maxDepth,
          totalNodes: newNodes.size,
          lastUpdate: Date.now()
        }
      }
    });
  },

  // 更新节点
  updateNode: (nodeId, updates) => {
    const { nodes } = get();
    const node = nodes.get(nodeId);
    if (!node) return;

    const updatedNode: RecursiveNode = {
      ...node,
      ...updates,
      metadata: { ...node.metadata, ...updates.metadata },
      uiState: { ...node.uiState, ...updates.uiState },
      recursionMeta: { ...node.recursionMeta, ...updates.recursionMeta }
    };

    const newNodes = new Map(nodes);
    newNodes.set(nodeId, updatedNode);

    set({ nodes: newNodes });
  },

  // 获取当前焦点节点
  getFocusNode: () => {
    const { viewState, nodes } = get();
    return nodes.get(viewState.focusNodeId);
  },

  // 获取节点
  getNode: (id) => {
    return get().nodes.get(id);
  }
}));
