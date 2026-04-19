/**
 * ConfigValidator 演示组件
 * 
 * 展示"规则约束配置，配置验证规则"的递归闭环思想：
 * 1. rules.md 定义架构原则
 * 2. config/index.ts 的业务配置必须符合这些原则
 * 3. ConfigValidator 运行时验证配置合规性
 * 4. rulesConfig 本身也是配置，可以被验证
 */

import { useState, useEffect } from 'react';
import { configValidator, rulesConfig, ValidationResult } from '../config';
import './ConfigValidatorDemo.css';

export function ConfigValidatorDemo() {
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    // 运行配置验证
    const validationResult = configValidator.validateAll();
    setResult(validationResult);
  }, []);

  if (!result) {
    return <div className="config-validator-demo loading">验证配置中...</div>;
  }

  return (
    <div className={`config-validator-demo ${result.valid ? 'valid' : 'invalid'}`}>
      <div className="validator-header" onClick={() => setExpanded(!expanded)}>
        <div className="validator-status">
          {result.valid ? '✅' : '⚠️'}
        </div>
        <div className="validator-title">
          <h3>配置-规则递归验证闭环</h3>
          <p className="validator-subtitle">
            {result.valid 
              ? '所有配置符合 rules.md 规范' 
              : `发现 ${result.summary.errors} 个错误，${result.summary.warnings} 个警告`
            }
          </p>
        </div>
        <div className="validator-toggle">{expanded ? '▼' : '▶'}</div>
      </div>

      {expanded && (
        <div className="validator-details">
          {/* 元配置信息 */}
          <div className="meta-config-section">
            <h4>📋 元配置 (rulesConfig)</h4>
            <div className="meta-info">
              <div className="meta-item">
                <span className="meta-label">版本:</span>
                <span className="meta-value">{rulesConfig.version}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">验证级别:</span>
                <span className="meta-value">{rulesConfig.validationLevel}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">核心原则:</span>
                <span className="meta-value">{rulesConfig.coreRulesPath}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">实现映射:</span>
                <span className="meta-value">{rulesConfig.implementationMapPath}</span>
              </div>
            </div>
          </div>

          {/* 原则检查点 */}
          <div className="principles-section">
            <h4>🛡️ 架构原则检查点</h4>
            <div className="principles-list">
              {Object.entries(rulesConfig.principles).map(([key, principle]) => (
                <div key={key} className={`principle-item ${principle.enabled ? 'enabled' : 'disabled'}`}>
                  <div className="principle-header">
                    <span className="principle-status">{principle.enabled ? '✓' : '✗'}</span>
                    <span className="principle-name">{key}</span>
                    {principle.required && <span className="principle-required">必需</span>}
                  </div>
                  <p className="principle-desc">{principle.description}</p>
                </div>
              ))}
            </div>
          </div>

          {/* 约束规则 */}
          <div className="constraints-section">
            <h4>🔗 配置约束规则</h4>
            <div className="constraints-list">
              {Object.entries(rulesConfig.constraints).map(([key, constraint]) => (
                <div key={key} className="constraint-item">
                  <span className="constraint-name">{key}</span>
                  <span className="constraint-desc">{constraint.description}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 验证结果 */}
          {result.errors.length > 0 && (
            <div className="validation-errors">
              <h4>🚨 验证问题</h4>
              <ul className="errors-list">
                {result.errors.map((error, index) => (
                  <li key={index} className={`error-item ${error.severity}`}>
                    <span className="error-severity">[{error.severity.toUpperCase()}]</span>
                    <span className="error-path">{error.path}</span>
                    <span className="error-principle">({error.principle})</span>
                    <p className="error-message">{error.message}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 递归验证说明 */}
          <div className="recursive-explanation">
            <h4>🔄 递归验证闭环</h4>
            <div className="recursive-flow">
              <div className="flow-step">
                <div className="flow-box">rules.md</div>
                <div className="flow-arrow">↓ 定义规范</div>
              </div>
              <div className="flow-step">
                <div className="flow-box">config/index.ts</div>
                <div className="flow-arrow">↓ 业务配置</div>
              </div>
              <div className="flow-step">
                <div className="flow-box">ConfigValidator</div>
                <div className="flow-arrow">↓ 运行时验证</div>
              </div>
              <div className="flow-step">
                <div className="flow-box">rulesConfig</div>
                <div className="flow-arrow">↓ 元验证</div>
              </div>
              <div className="flow-step">
                <div className="flow-box highlight">闭环完成 ✓</div>
              </div>
            </div>
            <p className="recursive-note">
              本组件本身也是配置的消费者，其样式和行为受 uiConfig 约束，
              同时验证 uiConfig 是否符合 rules.md 的弱耦合原则。
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default ConfigValidatorDemo;
