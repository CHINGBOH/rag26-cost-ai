/**
 * 聊天控制面板 - 滑出式
 * 模型选择、参数调节、RAG配置
 * 完全配置驱动 - 所有参数范围和选项从 config/index.ts 读取
 */

import { useState } from 'react';
import { chatFlowConfig, modelParamsConfig, ragParamsConfig } from '../../config';
import {
  ChatConfig,
  InferenceEngine,
  PROVIDER_OPTIONS,
  ENGINE_OPTIONS,
  MODEL_OPTIONS,
  CHAT_PRESETS,
  ChatPreset
} from '@rag/shared';

interface ChatControlPanelProps {
  config: ChatConfig;
  onConfigChange: (config: Partial<ChatConfig>) => void;
  isOpen: boolean;
  onClose: () => void;
}

export const ChatControlPanel: React.FC<ChatControlPanelProps> = ({
  config,
  onConfigChange,
  isOpen,
  onClose
}) => {
  const [activeTab, setActiveTab] = useState<'model' | 'params' | 'rag'>('model');

  const applyPreset = (preset: ChatPreset) => {
    onConfigChange(preset.config);
  };

  // 从配置生成参数滑块定义
  const modelParamSliders = [
    { key: 'temperature', label: 'Temperature', config: modelParamsConfig.temperature },
    { key: 'maxTokens', label: 'Max Tokens', config: modelParamsConfig.maxTokens },
    { key: 'topP', label: 'Top P', config: modelParamsConfig.topP },
    { key: 'frequencyPenalty', label: 'Frequency Penalty', config: modelParamsConfig.frequencyPenalty },
    { key: 'presencePenalty', label: 'Presence Penalty', config: modelParamsConfig.presencePenalty },
  ] as const;

  const ragParamSliders = [
    { key: 'topK', label: '召回数量 (Top-K)', config: ragParamsConfig.topK },
    { key: 'threshold', label: '相似度阈值', config: ragParamsConfig.threshold },
    { key: 'maxReferences', label: '最大引用数', config: ragParamsConfig.maxReferences },
  ] as const;

  return (
    <>
      {/* 遮罩层 */}
      <div 
        className={`control-panel-overlay ${isOpen ? 'open' : ''}`}
        onClick={onClose}
      />
      
      {/* 滑出面板 */}
      <div className={`control-panel ${isOpen ? 'open' : ''}`}>
        <div className="control-panel-header">
          <span className="control-panel-title">⚙️ 设置</span>
          <button className="control-panel-close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="control-panel-content">
          {/* 预设选择 */}
          <div className="control-section">
            <div className="control-section-title">快速预设</div>
            <div className="provider-grid">
              {CHAT_PRESETS.map(preset => (
                <button
                  key={preset.id}
                  className="provider-btn"
                  onClick={() => applyPreset(preset)}
                  title={preset.description}
                >
                  <span className="provider-icon">{preset.icon}</span>
                  <span className="provider-label">{preset.name}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 标签页切换 */}
          <div className="control-section">
            <div className="tab-buttons">
              {(['model', 'params', 'rag'] as const).map(tab => (
                <button
                  key={tab}
                  className={`tab-btn ${activeTab === tab ? 'active' : ''}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === 'model' ? chatFlowConfig.ui.tabs.model : tab === 'params' ? chatFlowConfig.ui.tabs.params : chatFlowConfig.ui.tabs.rag}
                </button>
              ))}
            </div>
          </div>

          {/* 模型设置 */}
          {activeTab === 'model' && (
            <div className="control-section">
              {/* 提供方选择 */}
              <div className="control-section-title">LLM 提供方</div>
              <div className="provider-grid">
                {PROVIDER_OPTIONS.map(provider => (
                  <button
                    key={provider.value}
                    className={`provider-btn ${config.provider === provider.value ? 'active' : ''}`}
                    onClick={() => onConfigChange({ provider: provider.value })}
                  >
                    <span className="provider-icon">{provider.icon}</span>
                    <span className="provider-label">{provider.label}</span>
                  </button>
                ))}
              </div>

              {/* 模型选择 */}
              <div className="control-select-wrapper">
                <div className="control-section-title">模型</div>
                <select 
                  className="control-select"
                  value={config.model}
                  onChange={(e) => onConfigChange({ model: e.target.value })}
                >
                  {MODEL_OPTIONS[config.provider]?.map(model => (
                    <option key={model} value={model}>{model}</option>
                  ))}
                </select>
              </div>

              {/* 推理引擎 */}
              <div className="control-select-wrapper">
                <div className="control-section-title">推理引擎</div>
                <select 
                  className="control-select"
                  value={config.engine || 'default'}
                  onChange={(e) => onConfigChange({ engine: e.target.value as InferenceEngine })}
                >
                  {ENGINE_OPTIONS.map(engine => (
                    <option key={engine.value} value={engine.value}>{engine.label}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* 生成参数 - 配置驱动 */}
          {activeTab === 'params' && (
            <div className="control-section">
              {modelParamSliders.map(({ key, label, config: paramConfig }) => (
                <SliderControl
                  key={key}
                  label={label}
                  value={config[key as keyof ChatConfig] as number}
                  min={paramConfig.min}
                  max={paramConfig.max}
                  step={paramConfig.step}
                  description={paramConfig.description}
                  onChange={(v) => onConfigChange({ [key]: v })}
                />
              ))}
            </div>
          )}

          {/* RAG 参数 - 配置驱动 */}
          {activeTab === 'rag' && (
            <div className="control-section">
              {/* 启用 RAG */}
              <div className="toggle-control">
                <label>启用 RAG 检索</label>
                <div 
                  className={`toggle-switch ${config.enableRag ? 'active' : ''}`}
                  onClick={() => onConfigChange({ enableRag: !config.enableRag })}
                />
              </div>

              {config.enableRag && (
                <>
                  {ragParamSliders.map(({ key, label, config: paramConfig }) => (
                    <SliderControl
                      key={key}
                      label={label}
                      value={config.ragParams[key as keyof typeof config.ragParams] as number}
                      min={paramConfig.min}
                      max={paramConfig.max}
                      step={paramConfig.step}
                      description={paramConfig.description}
                      onChange={(v) => onConfigChange({
                        ragParams: { ...config.ragParams, [key]: v }
                      })}
                    />
                  ))}

                  <div className="toggle-control">
                    <label>启用精排 (Rerank)</label>
                    <div 
                      className={`toggle-switch ${config.ragParams.rerank ? 'active' : ''}`}
                      onClick={() => onConfigChange({
                        ragParams: { ...config.ragParams, rerank: !config.ragParams.rerank }
                      })}
                    />
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
};

// 滑块控件
interface SliderControlProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  description?: string;
  onChange: (value: number) => void;
}

const SliderControl: React.FC<SliderControlProps> = ({
  label,
  value,
  min,
  max,
  step,
  description,
  onChange
}) => {
  return (
    <div className="slider-control">
      <label>
        <span>{label}</span>
        <span>{value}</span>
      </label>
      {description && (
        <span className="slider-description">
          {description}
        </span>
      )}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
    </div>
  );
};
