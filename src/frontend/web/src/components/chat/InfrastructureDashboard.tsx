/**
 * 基础设施看板
 * 显示 llama.cpp、vLLM、LLM Providers、API 状态的核心看板
 */

import { useEffect, useState } from 'react';
import { getActiveLLMConfig, uiConfig } from '../../config';

// 服务状态类型
interface ServiceStatus {
  id: string;
  name: string;
  type: 'llm' | 'inference' | 'api' | 'database';
  status: 'healthy' | 'degraded' | 'down' | 'unknown';
  icon: string;
  metrics: {
    label: string;
    value: string;
    trend?: 'up' | 'down' | 'stable';
  }[];
  active?: boolean;
}

interface InfrastructureDashboardProps {
  activeProvider: string;
  activeEngine: string;
}

export const InfrastructureDashboard: React.FC<InfrastructureDashboardProps> = ({
  activeProvider,
  activeEngine
}) => {
  // 从配置生成服务列表
  const generateServices = (): ServiceStatus[] => {
    const activeLLM = getActiveLLMConfig();
    
    return [
      // 当前激活的 LLM
      {
        id: `llm-${activeLLM.id}`,
        name: activeLLM.name,
        type: 'llm',
        status: 'healthy',
        icon: activeLLM.icon,
        active: true,
        metrics: [
          { label: '延迟', value: '180ms', trend: 'stable' },
          { label: '模型', value: activeLLM.defaultModel },
          { label: '队列', value: '0' }
        ]
      },
      // llama.cpp 引擎
      {
        id: 'engine-llamacpp',
        name: 'llama.cpp',
        type: 'inference',
        status: activeEngine?.includes('llama') ? 'healthy' : 'unknown',
        icon: '🦙',
        active: activeEngine?.includes('llama'),
        metrics: [
          { label: 'GPU', value: activeEngine?.includes('llama') ? '78%' : '-' },
          { label: 'VRAM', value: activeEngine?.includes('llama') ? '14.2GB' : '-' },
          { label: 'tok/s', value: activeEngine?.includes('llama') ? '45' : '-' }
        ]
      },
      // vLLM 引擎
      {
        id: 'engine-vllm',
        name: 'vLLM',
        type: 'inference',
        status: activeEngine === 'vllm' ? 'healthy' : 'unknown',
        icon: '⚡',
        active: activeEngine === 'vllm',
        metrics: [
          { label: 'GPU', value: activeEngine === 'vllm' ? '85%' : '-', trend: 'stable' },
          { label: 'VRAM', value: activeEngine === 'vllm' ? '18.5GB' : '-' },
          { label: '吞吐', value: activeEngine === 'vllm' ? '120' : '-' }
        ]
      },
      // API Gateway
      {
        id: 'api-gateway',
        name: 'API Gateway',
        type: 'api',
        status: 'healthy',
        icon: '🔌',
        metrics: [
          { label: 'QPS', value: '156', trend: 'up' },
          { label: '错误率', value: '0.01%' },
          { label: 'P99', value: '320ms' }
        ]
      },
      // Vector DB
      {
        id: 'db-vector',
        name: 'Vector DB',
        type: 'database',
        status: 'healthy',
        icon: '🔍',
        metrics: [
          { label: '文档数', value: '2.4M' },
          { label: '索引', value: '12' },
          { label: '延迟', value: '12ms' }
        ]
      }
    ];
  };

  const [services, setServices] = useState<ServiceStatus[]>(generateServices());

  // 配置变化时更新服务
  useEffect(() => {
    setServices(generateServices());
  }, [activeProvider, activeEngine]);

  // 模拟实时更新
  useEffect(() => {
    const interval = setInterval(() => {
      setServices(prev => prev.map(s => {
        if (s.type === 'inference' && s.active) {
          return {
            ...s,
            metrics: s.metrics.map(m => {
              if (m.label === 'GPU') {
                const current = parseInt(m.value) || 50;
                const newVal = Math.max(
                  uiConfig.infrastructure.gpuMin, 
                  Math.min(uiConfig.infrastructure.gpuMax, 
                    current + Math.floor(Math.random() * 10) - 5)
                );
                return { ...m, value: `${newVal}%` };
              }
              if (m.label === 'tok/s' || m.label === '吞吐') {
                const current = parseInt(m.value) || 40;
                const newVal = Math.max(
                  uiConfig.infrastructure.tokensMin, 
                  Math.min(uiConfig.infrastructure.tokensMax, 
                    current + Math.floor(Math.random() * 6) - 3)
                );
                return { ...m, value: `${newVal}` };
              }
              return m;
            })
          };
        }
        if (s.type === 'api') {
          return {
            ...s,
            metrics: s.metrics.map(m => {
              if (m.label === 'QPS') {
                const current = parseInt(m.value) || 100;
                const newVal = Math.max(
                  uiConfig.infrastructure.qpsMin, 
                  Math.min(uiConfig.infrastructure.qpsMax, 
                    current + Math.floor(Math.random() * 20) - 10)
                );
                return { ...m, value: `${newVal}` };
              }
              return m;
            })
          };
        }
        return s;
      }));
    }, uiConfig.infrastructure.updateInterval);

    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status: ServiceStatus['status']) => {
    switch (status) {
      case 'healthy': return 'var(--color-success)';
      case 'degraded': return 'var(--color-warning)';
      case 'down': return 'var(--color-error)';
      default: return 'var(--text-muted)';
    }
  };

  const getTrendIcon = (trend?: string) => {
    switch (trend) {
      case 'up': return '↑';
      case 'down': return '↓';
      default: return '→';
    }
  };

  return (
    <div className="infrastructure-dashboard">
      <div className="dashboard-header">
        <span className="dashboard-title">🏗️ 基础设施状态</span>
        <span className="dashboard-subtitle">
          LLM · 推理引擎 · API · 数据库
        </span>
      </div>
      
      <div className="services-grid">
        {services.map(service => (
          <div 
            key={service.id}
            className={`service-card ${service.active ? 'active' : ''} ${service.status}`}
          >
            <div className="service-header">
              <span className="service-icon">{service.icon}</span>
              <span className="service-name">{service.name}</span>
              <span 
                className="service-status-dot"
                style={{ background: getStatusColor(service.status) }}
              />
              {service.active && <span className="active-badge">运行中</span>}
            </div>
            
            <div className="service-metrics">
              {service.metrics.map((metric, idx) => (
                <div key={idx} className="metric-item">
                  <span className="metric-label">{metric.label}</span>
                  <span className="metric-value">
                    {metric.value}
                    {metric.trend && (
                      <span className={`metric-trend ${metric.trend}`}>
                        {getTrendIcon(metric.trend)}
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
