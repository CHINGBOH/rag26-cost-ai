/**
 * 数据管道页 — 文档上传 + 知识库运行状态
 * 仅渲染 health 接口实际返回的服务，不再硬编码 Elasticsearch / Neo4j
 */

import { useState, useRef, useEffect } from 'react';
import { checkHealth, HealthResponse } from '../services/agentApi';
import { PageHeader } from '../components/common/PageHeader';
import { StatusDot } from '../components/common/StatusDot';
import './PipelinePage.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

const SERVICE_LABELS: Record<string, string> = {
  postgres: 'PostgreSQL',
  postgresql: 'PostgreSQL',
  qdrant: 'Qdrant 向量库',
  cache: '缓存',
  redis: 'Redis',
  vector: '向量索引',
  keyword: '全文索引',
};

export const PipelinePage: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

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

  const services = health?.services
    ? Object.entries(health.services).map(([k, v]) => ({
        key: k,
        label: SERVICE_LABELS[k] || k,
        status: typeof v === 'string' ? v : 'unknown',
      }))
    : [];

  return (
    <div className="pipeline-page">
      <PageHeader title="数据管道" subtitle="文档上传与知识库运行状态" />

      <div className="pipeline-grid">
        <section className="pipeline-card">
          <h2>知识库连通性</h2>
          {health ? (
            <div className="health-grid">
              {services.map((s) => (
                <div key={s.key} className="health-item">
                  <StatusDot status={s.status} />
                  <span className="health-label">{s.label}</span>
                  <span className="health-status">{s.status}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="loading-text">加载中…</p>
          )}
          {health && (
            <div className="health-footer">
              整体 <strong>{health.status}</strong>
              <span className="health-time">
                更新于 {new Date(health.timestamp).toLocaleTimeString()}
              </span>
            </div>
          )}
        </section>

        <section className="pipeline-card">
          <h2>文档上传</h2>
          <div className="upload-zone" onClick={() => fileRef.current?.click()}>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.docx"
              onChange={(e) => {
                setFile(e.target.files?.[0] || null);
                setUploadResult(null);
              }}
              hidden
            />
            {file ? (
              <div className="file-info">
                <span className="file-name">{file.name}</span>
                <span className="file-size">{(file.size / 1024).toFixed(0)} KB</span>
              </div>
            ) : (
              <div className="upload-hint">
                <span>点击选择文件</span>
                <span className="hint-formats">PDF · PNG · JPG · DOCX</span>
              </div>
            )}
          </div>

          {file && (
            <button className="upload-btn" onClick={handleUpload} disabled={uploading}>
              {uploading ? '处理中…' : '上传并处理'}
            </button>
          )}

          {uploadResult && (
            <div className={`upload-result ${uploadResult.ok ? 'success' : 'error'}`}>
              {uploadResult.msg}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};
