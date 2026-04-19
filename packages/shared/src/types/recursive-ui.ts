/**
 * 递归UI类型定义
 * 每一层都是自我相似的结构
 */

import { RetrievedChunk, ExpertJudgmentResponse } from './recursion';

/**
 * 递归节点 - 核心抽象
 * 任何可展示的内容都是一个节点，节点可以包含子节点
 */
export interface RecursiveNode {
  id: string;
  type: 'answer' | 'claim' | 'evidence' | 'source' | 'contradiction' | 'user-branch';
  
  // 当前层内容
  content: string;
  metadata: NodeMetadata;
  
  // 递归结构
  children: RecursiveNode[];      // 支撑/反驳的子节点
  parent?: string;                // 父节点ID（用于返回）
  
  // 元认知层
  recursionMeta: {
    depth: number;                // 当前深度
    path: string[];               // 从根到当前的路径
    informationGain: number;      // 相比父节点的信息增益
    confidence: number;           // 该节点的置信度
    expertJudgment?: ExpertJudgmentResponse;
  };
  
  // 交互状态
  uiState: {
    expanded: boolean;            // 是否展开子节点
    selected: boolean;            // 是否被选中
    userModified: boolean;        // 是否被用户修改过
    branchFrom?: string;          // 如果是用户分叉，记录来源
  };
}

export interface NodeMetadata {
  timestamp: number;
  source?: string;                // 来源文档/URL
  author?: 'system' | 'user' | 'llm' | 'external';
  tags: string[];
  // 类型特定的元数据
  chunkInfo?: RetrievedChunk;
  judgmentInfo?: ExpertJudgmentResponse;
}

/**
 * 递归视图状态
 * 管理当前视野（类似显微镜的焦距）
 */
export interface RecursiveViewState {
  // 当前焦点节点
  focusNodeId: string;
  
  // 视野历史（用于返回）
  history: string[];
  
  // 并行分支
  branches: Map<string, RecursiveBranch>;
  
  // 全局元信息
  globalMeta: {
    maxDepthReached: number;
    totalNodes: number;
    userBranches: number;
    lastUpdate: number;
  };
}

/**
 * 用户分叉分支
 */
export interface RecursiveBranch {
  id: string;
  name: string;                   // 用户给分支起的名字
  forkedFrom: string;             // 从哪个节点分叉
  forkedAt: number;               // 分叉时间
  
  // 分支有自己的根节点
  rootNode: RecursiveNode;
  
  // 分支状态
  status: 'active' | 'merged' | 'discarded';
  
  // 如果已合并，记录合并回主线的位置
  mergedTo?: string;
}

/**
 * 递归事件 - 用于UI更新
 */
export type RecursiveUIEvent =
  | { type: 'node_expanded'; nodeId: string; children: RecursiveNode[] }
  | { type: 'node_collapsed'; nodeId: string }
  | { type: 'focus_changed'; from: string; to: string; path: string[] }
  | { type: 'branch_created'; branch: RecursiveBranch }
  | { type: 'branch_merged'; branchId: string; to: string }
  | { type: 'user_annotated'; nodeId: string; annotation: string }
  | { type: 'drill_down'; from: RecursiveNode; to: RecursiveNode }
  | { type: 'climb_up'; from: RecursiveNode; to: RecursiveNode };

/**
 * 节点渲染配置
 * 同一节点在不同深度可以有不同的展示方式
 */
export interface NodeRenderConfig {
  // 根据深度决定展示粒度
  depthConfig: Map<number, {
    showChildren: boolean;        // 是否显示子节点
    maxChildren: number;          // 最多显示多少子节点
    showMetadata: boolean;        // 是否显示元数据
    showExpertJudgment: boolean;  // 是否显示专家判断
    contentTruncate: number;      // 内容截断长度
  }>;
  
  // 默认配置
  default: {
    showChildren: true;
    maxChildren: 5;
    showMetadata: true;
    showExpertJudgment: true;
    contentTruncate: 500;
  };
}

/**
 * 递归操作
 */
export interface RecursiveOperations {
  // 下钻（进入子节点）
  drillDown: (nodeId: string) => void;
  
  // 上爬（返回父节点）
  climbUp: () => void;
  
  // 跳转到指定路径
  jumpTo: (path: string[]) => void;
  
  // 创建用户分支
  createBranch: (fromNodeId: string, name: string) => RecursiveBranch;
  
  // 合并分支回主线
  mergeBranch: (branchId: string, toNodeId: string) => void;
  
  // 用户标注
  annotate: (nodeId: string, annotation: string) => void;
  
  // 展开/折叠
  toggleExpand: (nodeId: string) => void;
}
