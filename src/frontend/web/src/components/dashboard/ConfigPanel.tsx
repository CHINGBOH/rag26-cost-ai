/**
 * 配置管理面板
 * 展示和修改系统配置
 * 
 * 注意：本面板本身也是配置驱动的，体现"递归配置"思想
 * 其布局和行为受 uiConfig 约束，同时通过 ConfigValidator 验证配置合规性
 */

import { useState } from 'react';
import './Dashboard.css';
import { ConfigValidatorDemo } from '../ConfigValidatorDemo';

interface ConfigSection {
  id: string;
  title: string;
  description: string;
  settings: ConfigSetting[];
}

interface ConfigSetting {
  key: string;
  label: string;
  type: 'number' | 'string' | 'boolean' | 'select';
  value: any;
  min?: number;
  max?: number;
  options?: { label: string; value: any }[];
  description?: string;
}

const STORAGE_KEY = 'rag_dashboard_config_panel';

function loadInitialConfigs(defaults: ConfigSection[]): ConfigSection[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return defaults;
    const parsed: ConfigSection[] = JSON.parse(stored);
    // Merge: keep default structure, overwrite values from storage
    return defaults.map(section => {
      const storedSection = parsed.find(s => s.id === section.id);
      if (!storedSection) return section;
      return {
        ...section,
        settings: section.settings.map(setting => {
          const storedSetting = storedSection.settings.find(s => s.key === setting.key);
          return storedSetting ? { ...setting, value: storedSetting.value } : setting;
        }),
      };
    });
  } catch {
    return defaults;
  }
}

export const ConfigPanel: React.FC = () => {
  const defaultConfigs: ConfigSection[] = [
    {
      id: 'recursion',
      title: '🔁 递归控制',
      description: '控制递归检索的深度和边界条件',
      settings: [
        {
          key: 'maxDepth',
          label: '最大递归深度',
          type: 'number',
          value: 15,
          min: 1,
          max: 50,
          description: '超过此深度将强制人工审核'
        },
        {
          key: 'earlyStopThreshold',
          label: '早停阈值',
          type: 'number',
          value: 0.05,
          min: 0.01,
          max: 0.5,
          description: '信息增益低于此值时停止'
        },
        {
          key: 'compactionTrigger',
          label: '压缩触发比例',
          type: 'number',
          value: 0.6,
          min: 0.3,
          max: 0.9,
          description: '上下文达到此比例时触发压缩'
        }
      ]
    },
    {
      id: 'llm',
      title: '🤖 LLM 配置',
      description: '大语言模型相关配置',
      settings: [
        {
          key: 'temperature',
          label: 'Temperature',
          type: 'number',
          value: 0.3,
          min: 0,
          max: 2,
          description: '低值更确定，高值更创造性'
        },
        {
          key: 'maxTokens',
          label: '最大 Token 数',
          type: 'number',
          value: 2000,
          min: 100,
          max: 8000,
          description: '单次生成的最大 token 数'
        },
        {
          key: 'expertJudgmentModel',
          label: '专家判断模型',
          type: 'select',
          value: 'kimi-for-coding',
          options: [
            { label: 'Kimi for Coding', value: 'kimi-for-coding' },
            { label: 'GPT-4', value: 'gpt-4' },
            { label: 'Claude', value: 'claude-3' }
          ]
        }
      ]
    },
    {
      id: 'retrieval',
      title: '🔍 检索配置',
      description: '检索策略和参数',
      settings: [
        {
          key: 'topK',
          label: 'Top-K 召回',
          type: 'number',
          value: 100,
          min: 10,
          max: 500,
          description: '每库召回的文档数'
        },
        {
          key: 'rerankTopK',
          label: '精排后 Top-K',
          type: 'number',
          value: 20,
          min: 5,
          max: 100,
          description: '精排后保留的文档数'
        },
        {
          key: 'similarityThreshold',
          label: '相似度阈值',
          type: 'number',
          value: 0.7,
          min: 0,
          max: 1,
          description: '低于此值的文档将被过滤'
        },
        {
          key: 'enableReranking',
          label: '启用精排',
          type: 'boolean',
          value: true
        }
      ]
    },
    {
      id: 'yolo',
      title: '⚡ YOLO 模式',
      description: '自动编码和递归配置',
      settings: [
        {
          key: 'silenceThreshold',
          label: '沉默阈值',
          type: 'number',
          value: 30,
          min: 10,
          max: 300,
          description: '秒，无响应后触发 YOLO'
        },
        {
          key: 'maxRecursionDepth',
          label: 'YOLO 最大递归层数',
          type: 'number',
          value: 5,
          min: 1,
          max: 10,
          description: '自动编码的递归层数'
        },
        {
          key: 'enableRecursiveCoding',
          label: '启用递归编码',
          type: 'boolean',
          value: true
        }
      ]
    },
    {
      id: 'heartbeat',
      title: '💓 心跳监控',
      description: '实时状态推送配置',
      settings: [
        {
          key: 'heartbeatInterval',
          label: '心跳间隔',
          type: 'number',
          value: 2000,
          min: 500,
          max: 10000,
          description: '毫秒，Worker 心跳频率'
        },
        {
          key: 'pushInterval',
          label: '推送间隔',
          type: 'number',
          value: 1000,
          min: 500,
          max: 5000,
          description: '毫秒，状态推送频率'
        }
      ]
    }
  ];

  const [configs, setConfigs] = useState<ConfigSection[]>(() => loadInitialConfigs(defaultConfigs));
  const [saved, setSaved] = useState(false);

  const handleChange = (sectionId: string, key: string, value: any) => {
    setConfigs(prev => prev.map(section => {
      if (section.id !== sectionId) return section;
      return {
        ...section,
        settings: section.settings.map(setting => {
          if (setting.key !== key) return setting;
          return { ...setting, value };
        })
      };
    }));
    setSaved(false);
  };

  const handleSave = () => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(configs));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      alert('保存失败：' + (e instanceof Error ? e.message : String(e)));
    }
  };

  const handleReset = () => {
    if (confirm('确定要重置所有配置吗？')) {
      localStorage.removeItem(STORAGE_KEY);
      setConfigs(defaultConfigs);
      setSaved(false);
    }
  };

  return (
    <div className="config-panel">
      {/* 配置-规则递归验证闭环演示 */}
      <ConfigValidatorDemo />

      <div className="config-header">
        <p className="config-hint">
          修改配置后需要重启服务才能生效
        </p>
        <div className="config-actions">
          <button className="btn-secondary" onClick={handleReset}>
            重置
          </button>
          <button className="btn-primary" onClick={handleSave}>
            {saved ? '已保存 ✓' : '保存配置'}
          </button>
        </div>
      </div>

      <div className="config-sections">
        {configs.map(section => (
          <ConfigSectionView 
            key={section.id}
            section={section}
            onChange={handleChange}
          />
        ))}
      </div>
    </div>
  );
};

const ConfigSectionView: React.FC<{
  section: ConfigSection;
  onChange: (sectionId: string, key: string, value: any) => void;
}> = ({ section, onChange }) => {
  return (
    <section className="config-section">
      <div className="config-section-header">
        <h3 className="config-section-title">{section.title}</h3>
        <p className="config-section-desc">{section.description}</p>
      </div>
      
      <div className="config-settings">
        {section.settings.map(setting => (
          <ConfigSettingView
            key={setting.key}
            setting={setting}
            onChange={(value) => onChange(section.id, setting.key, value)}
          />
        ))}
      </div>
    </section>
  );
};

const ConfigSettingView: React.FC<{
  setting: ConfigSetting;
  onChange: (value: any) => void;
}> = ({ setting, onChange }) => {
  return (
    <div className="config-setting">
      <div className="setting-info">
        <label className="setting-label">{setting.label}</label>
        {setting.description && (
          <span className="setting-desc">{setting.description}</span>
        )}
      </div>
      
      <div className="setting-control">
        {setting.type === 'number' && (
          <input
            type="number"
            className="setting-input"
            value={setting.value}
            min={setting.min}
            max={setting.max}
            step={setting.value < 1 ? 0.01 : 1}
            onChange={(e) => onChange(parseFloat(e.target.value))}
          />
        )}
        
        {setting.type === 'string' && (
          <input
            type="text"
            className="setting-input"
            value={setting.value}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
        
        {setting.type === 'boolean' && (
          <label className="setting-toggle">
            <input
              type="checkbox"
              checked={setting.value}
              onChange={(e) => onChange(e.target.checked)}
            />
            <span className="toggle-slider" />
          </label>
        )}
        
        {setting.type === 'select' && setting.options && (
          <select
            className="setting-select"
            value={setting.value}
            onChange={(e) => onChange(e.target.value)}
          >
            {setting.options.map(opt => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
};
