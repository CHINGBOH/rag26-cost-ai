/**
 * 数据管道页
 * 文档上传 + 四库状态
 */

import { useState, useRef, useEffect } from 'react';
import { checkHealth, HealthResponse } from '../services/agentApi';
import './PipelinePage.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export const PipelinePage: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // 定时刷新健康状态
  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const h = await checkHealth();
        setHealth(h);
      } catch { /* ignore */ }
    };
    fetchHealth();
    const timer = setInterval(fetchHealth, 15000);
    return () => clearInterval(timer);
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('title', file.name);
      const res = await fetch(`${API_BASE}/api/v1/documents/process`, {
        method: 'POST',
        body: form,
      });
      if (!res.ok) throw new Error(`上传失败: ${res.status}`);
      const data = await res.json();
      setUploadResult({ ok: true, msg: `文档 ${data.doc_id || file.name} 已提交处理` });
      setFile(null);
      if (fileRef.current) fileRef.current.value = '';
    } catch (e: any) {
      setUploadResult({ ok: false, msg: e.message });
    } finally {
      setUploading(false);
    }
  };

  const statusIcon = (s: string) =>
    s === 'healthy' || s === 'ok' ? '🟢' :
    s === 'degraded' ? '🟡' : '🔴';

  return (
    <div className="pipeline-page">
      <h1>数据管道</h1>
      <p className="page-subtitle">文档上传与四库运行状态</p>

      <div className="pipeline-grid">
        {/* 四库状态 */}
        <section className="pipeline-card">
          <h2>四库状态</h2>
          {health ? (
            <div className="health-grid">
              <div className="health-item">
                <span className="health-icon">{statusIcon(health.services?.qdrant || health.services?.vector || 'unknown')}</span>
                <span className="health-label">Qdrant</span>
                <span className="health-status">{health.services?.qdrant || health.services?.vector || '—'}</span>
              </div>
              <div className="health-item">
                <span className="health-icon">{statusIcon(health.services?.elasticsearch || health.services?.keyword || 'unknown')}</span>
                <span className="health-label">Elasticsearch</span>
                <span className="health-status">{health.services?.elasticsearch || health.services?.keyword || '—'}</span>
              </div>
              <div className="health-item">
                <span className="health-icon">{statusIcon(health.services?.neo4j || health.services?.graph || 'unknown')}</span>
                <span className="health-label">Neo4j</span>
                <span className="health-status">{health.services?.neo4j || health.services?.graph || '—'}</span>
              </div>
              <div className="health-item">
                <span className="health-icon">{statusIcon(health.services?.redis || health.services?.cache || 'unknown')}</span>
                <span className="health-label">Redis</span>
                <span className="health-status">{health.services?.redis || health.services?.cache || '—'}</span>
              </div>
            </div>
          ) : (
            <p className="loading-text">加载中...</p>
          )}
          {health && (
            <div className="health-footer">
              整体: <strong>{health.status}</strong>
              <span className="health-time">更新于 {new Date(health.timestamp).toLocaleTimeString()}</span>
            </div>
          )}
        </section>

        {/* 文档上传 */}
        <section className="pipeline-card">
          <h2>文档上传</h2>
          <div
            className="upload-zone"
            onClick={() => fileRef.current?.click()}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.docx"
              onChange={e => { setFile(e.target.files?.[0] || null); setUploadResult(null); }}
              hidden
            />
            {file ? (
              <div className="file-info">
                <span className="file-icon">📄</span>
                <span>{file.name}</span>
                <span className="file-size">({(file.size / 1024).toFixed(0)} KB)</span>
              </div>
            ) : (
              <div className="upload-hint">
                <span>📁</span>
                <span>点击选择文件</span>
                <span className="hint-formats">PDF / PNG / JPG / DOCX</span>
              </div>
            )}
          </div>

          {file && (
            <button
              className="upload-btn"
              onClick={handleUpload}
              disabled={uploading}
            >
              {uploading ? '处理中...' : '⬆️ 上传并处理'}
            </button>
          )}

          {uploadResult && (
            <div className={`upload-result ${uploadResult.ok ? 'success' : 'error'}`}>
              {uploadResult.ok ? '✅' : '❌'} {uploadResult.msg}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};
