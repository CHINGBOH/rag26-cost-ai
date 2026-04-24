/**
 * 聊天输入组件 - 配置驱动版
 * 简洁的输入框 + 快捷工具 + 底部模型/温度控制栏
 * 所有参数从 config 读取，零硬编码
 */

import { useState, useRef, useCallback } from 'react';
import { 
  uiConfig, 
  chatFlowConfig, 
  inputBarConfig, 
  llmProviders,
  modelParamsConfig,
} from '../../config';

// UI 按钮配置 - 从配置读取
const BUTTONS = chatFlowConfig.ui.buttons;
const TOOLTIPS = chatFlowConfig.ui.tooltips;

interface ChatInputProps {
  onSend: (message: string, options?: { executeCode?: boolean }) => void;
  onClear?: () => void;
  disabled?: boolean;
  placeholder?: string;
  isLoading?: boolean;
  // 新增：模型和温度控制
  selectedModel?: string;
  onModelChange?: (model: string) => void;
  temperature?: number;
  onTemperatureChange?: (temp: number) => void;
  selectedProvider?: string;
  onSettingsClick?: () => void;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend,
  onClear,
  disabled,
  placeholder = '输入消息...',
  isLoading,
  // 模型和温度控制
  selectedModel,
  onModelChange,
  temperature,
  onTemperatureChange,
  selectedProvider = inputBarConfig.defaultProvider,
  onSettingsClick,
}) => {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 自动调整高度
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, uiConfig.inputArea.maxHeight)}px`;
    }
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    adjustHeight();
  };

  const handleSend = () => {
    if (!input.trim() || disabled || isLoading) return;
    onSend(input.trim());
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && chatFlowConfig.keyboard.sendOnEnter) {
      e.preventDefault();
      handleSend();
    }
  };

  // 获取当前 provider 配置
  const providerConfig = llmProviders[selectedProvider as keyof typeof llmProviders];
  const models = providerConfig?.models || [];
  const defaultModel = providerConfig?.defaultModel || '';
  const currentModel = selectedModel || defaultModel || (models[0]?.id ?? '');
  const currentTemp = temperature ?? providerConfig?.defaultParams?.temperature ?? modelParamsConfig.temperature.default;

  // 处理模型变更
  const handleModelChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newModel = e.target.value;
    onModelChange?.(newModel);
  };

  // 处理温度变更
  const handleTempChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newTemp = parseFloat(e.target.value);
    onTemperatureChange?.(newTemp);
  };

  // 应用快捷预设
  const applyPreset = (presetTemp: number) => {
    onTemperatureChange?.(presetTemp);
  };

  return (
    <div className="chat-input-wrapper">
      {/* 输入框主体 */}
      <div className="chat-input">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled || isLoading}
          rows={uiConfig.inputArea.rows}
        />
        
        <div className="input-actions">
          {onClear && (
            <button 
              className="clear-btn"
              onClick={onClear}
              disabled={disabled || isLoading}
              title={TOOLTIPS.clearChat}
            >
              {BUTTONS.clear}
            </button>
          )}
          <button 
            className="send-btn"
            onClick={handleSend}
            disabled={disabled || isLoading || !input.trim()}
            title={TOOLTIPS.send}
          >
            {isLoading ? BUTTONS.loading : BUTTONS.send}
          </button>
        </div>
      </div>

      {/* 底部控制栏 - 配置驱动 */}
      {inputBarConfig.enabled && (
        <div className="input-control-bar">
          {/* 模型选择器 */}
          {inputBarConfig.modelSelector.enabled && (
            <div className="control-item model-selector">
              {inputBarConfig.modelSelector.showIcon && (
                <span className="provider-icon">{providerConfig?.icon || '🤖'}</span>
              )}
              <select 
                className="control-select"
                value={currentModel}
                onChange={handleModelChange}
                style={{ width: inputBarConfig.modelSelector.width }}
              >
                {models.length > 0 ? (
                  models.map(model => (
                    <option key={model.id} value={model.id}>
                      {model.name}
                    </option>
                  ))
                ) : (
                  <option value="">-- 无可用模型 --</option>
                )}
              </select>
            </div>
          )}

          {/* 温度滑块 */}
          {inputBarConfig.temperatureSlider.enabled && (
            <div className="control-item temperature-control">
              {inputBarConfig.temperatureSlider.showLabel && (
                <span className="control-label">
                  {inputBarConfig.temperatureSlider.label}
                </span>
              )}
              <input
                type="range"
                className="temperature-slider"
                min={inputBarConfig.temperatureSlider.min}
                max={inputBarConfig.temperatureSlider.max}
                step={inputBarConfig.temperatureSlider.step}
                value={currentTemp}
                onChange={handleTempChange}
                style={{ width: inputBarConfig.temperatureSlider.width }}
              />
              {inputBarConfig.temperatureSlider.showValue && (
                <span className="temperature-value">{currentTemp.toFixed(1)}</span>
              )}
            </div>
          )}

          {/* 快捷预设按钮 */}
          {inputBarConfig.quickSettings.enabled && (
            <div className="control-item quick-presets">
              {inputBarConfig.quickSettings.presets.map(preset => (
                <button
                  key={preset.name}
                  className={`preset-btn ${currentTemp === preset.temperature ? 'active' : ''}`}
                  onClick={() => applyPreset(preset.temperature)}
                  title={`${preset.name}: T=${preset.temperature}`}
                >
                  <span className="preset-icon">{preset.icon}</span>
                  <span className="preset-name">{preset.name}</span>
                </button>
              ))}
            </div>
          )}

          {/* 高级设置按钮 */}
          {inputBarConfig.advancedSettings.enabled && onSettingsClick && (
            <div className="control-item">
              <button 
                className="settings-btn-small"
                onClick={onSettingsClick}
                title={inputBarConfig.advancedSettings.label}
              >
                <span>{inputBarConfig.advancedSettings.icon}</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// 快速提示按钮 - 从配置导入
import { quickPrompts } from '../../config';

interface QuickPrompt {
  icon: string;
  title: string;
  desc: string;
  prompt: string;
}

const QUICK_PROMPTS: QuickPrompt[] = quickPrompts.map(p => ({
  icon: p.icon,
  title: p.title,
  desc: p.description,
  prompt: p.prompt
}));

export const QuickPromptButtons: React.FC<{
  onSelect: (prompt: string) => void;
}> = ({ onSelect }) => {
  return (
    <div className="quick-prompt-buttons">
      {QUICK_PROMPTS.map((item, index) => (
        <button
          key={index}
          className="quick-prompt-btn"
          onClick={() => onSelect(item.prompt)}
        >
          <span className="icon">{item.icon}</span>
          <span className="text">
            <span className="title">{item.title}</span>
            <span className="desc">{item.desc}</span>
          </span>
        </button>
      ))}
    </div>
  );
};

// 模型信息条 - 简化版，保留向后兼容
interface ModelInfoBarProps {
  provider?: string;
  model?: string;
  temperature?: number;
  onSettingsClick?: () => void;
}

import { activeProvider } from '../../config';

const getProviderConfig = (providerId: string) => {
  return llmProviders[providerId as keyof typeof llmProviders];
};

export const ModelInfoBar: React.FC<ModelInfoBarProps> = ({
  provider,
  model,
  temperature,
  onSettingsClick
}) => {
  // 使用传入值或配置的当前 provider
  const currentProviderId = provider || activeProvider;
  const providerConfig = getProviderConfig(currentProviderId);
  
  // 使用传入值或配置默认值
  const displayIcon = providerConfig?.icon || '🤖';
  const displayName = providerConfig?.name || currentProviderId;
  const displayModel = model || providerConfig?.defaultModel || 'unknown';
  const displayTemp = temperature ?? providerConfig?.defaultParams?.temperature ?? 0.7;

  const formatModelName = (name: string) => {
    if (!name) return 'Unknown';
    if (name.length > uiConfig.messages.modelNameMaxLength) {
      return name.substring(0, uiConfig.messages.modelNameTruncateTo) + '...';
    }
    return name;
  };

  return (
    <div className="model-info-bar">
      <div className="model-info-main">
        <span className="model-provider-icon">
          {displayIcon}
        </span>
        <div className="model-info-text">
          <span className="model-name">{formatModelName(displayModel)}</span>
          <span className="model-config">
            {displayName} · T={displayTemp}
          </span>
        </div>
      </div>
      {onSettingsClick && (
        <button 
          className="settings-btn"
          onClick={onSettingsClick}
        >
          ⚙️ 设置
        </button>
      )}
    </div>
  );
};
