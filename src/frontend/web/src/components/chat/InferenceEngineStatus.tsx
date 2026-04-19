/**
 * 推理引擎状态组件
 * 显示 llama.cpp / vLLM / TGI / Ollama 等引擎的实时状态
 */

import { useEffect, useState } from 'react';
import { llmProviders } from '../../config';

// 从配置获取 provider 图标
const getProviderIcon = (type: string): string => {
  const provider = llmProviders[type as keyof typeof llmProviders];
  if (provider) return provider.icon;
  
  // 回退到引擎特定图标
  const engineIcons: Record<string, string> = {
    'llama.cpp': '🦙',
    'vllm': '⚡',
    'tensorrt': '🔥',
    'ollama': '🦙',
    'tgi': '🚀',
    'default': '🤖'
  };
  return engineIcons[type] || engineIcons['default'];
};

interface EngineStatus {
  id: string;
  type: string;
  name: string;
  status: 'idle' | 'loading' | 'active' | 'error';
  gpuUsage?: number;
  vramUsed?: number;
  vramTotal?: number;
  temperature?: number;
  tokensPerSecond?: number;
  queueLength?: number;
  modelLoaded?: string;
}

export const InferenceEngineStatus: React.FC = () => {
  const [engines, setEngines] = useState<EngineStatus[]>([
    {
      id: 'llama-1',
      type: 'llama.cpp',
      name: 'llama.cpp',
      status: 'active',
      gpuUsage: 85,
      vramUsed: 8192,
      vramTotal: 24576,
      temperature: 72,
      tokensPerSecond: 45,
      modelLoaded: 'llama-3-8b-q4'
    },
    {
      id: 'vllm-1',
      type: 'vllm',
      name: 'vLLM',
      status: 'idle',
      gpuUsage: 0,
      vramUsed: 0,
      vramTotal: 24576,
      modelLoaded: undefined
    }
  ]);

  // 模拟状态更新
  useEffect(() => {
    const interval = setInterval(() => {
      setEngines(prev => prev.map(engine => ({
        ...engine,
        gpuUsage: engine.status === 'active' 
          ? Math.max(30, Math.min(100, (engine.gpuUsage || 0) + (Math.random() - 0.5) * 10))
          : 0,
        vramUsed: engine.status === 'active'
          ? Math.max(4096, Math.min(16384, (engine.vramUsed || 0) + (Math.random() - 0.5) * 200))
          : 0,
        tokensPerSecond: engine.status === 'active'
          ? Math.max(20, Math.min(100, (engine.tokensPerSecond || 0) + (Math.random() - 0.5) * 5))
          : 0,
        temperature: engine.status === 'active'
          ? Math.max(60, Math.min(85, (engine.temperature || 70) + (Math.random() - 0.5) * 3))
          : 35
      })));
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  const formatBytes = (mb: number) => {
    if (mb >= 1024) {
      return `${(mb / 1024).toFixed(1)} GB`;
    }
    return `${Math.round(mb)} MB`;
  };

  return (
    <div className="inference-engine-status">
      {engines.map(engine => (
        <div 
          key={engine.id}
          className={`engine-status-item ${engine.status}`}
          title={`${engine.name} - ${engine.modelLoaded || '未加载模型'}`}
        >
          <span className="engine-icon">
            {getProviderIcon(engine.type)}
          </span>
          <span className="engine-name">{engine.name}</span>
          
          {engine.status === 'active' && (
            <>
              <span className="engine-metric gpu">
                GPU: {Math.round(engine.gpuUsage || 0)}%
              </span>
              <span className="engine-metric vram">
                VRAM: {formatBytes(engine.vramUsed || 0)}
              </span>
              <span className="engine-metric tps">
                {Math.round(engine.tokensPerSecond || 0)} tok/s
              </span>
            </>
          )}
          
          {engine.status === 'idle' && (
            <span className="engine-metric idle">空闲</span>
          )}
          
          {engine.status === 'loading' && (
            <span className="engine-metric loading">加载中...</span>
          )}
        </div>
      ))}
    </div>
  );
};
