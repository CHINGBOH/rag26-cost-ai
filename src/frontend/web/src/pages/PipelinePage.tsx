/**
 * 数据管道页 — 一键上传 → OCR → 切块 → 嵌入 → 入库；任务监控
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { getLiveArchitecture, LiveArchitecture } from '../services/ragApi';
import {
  pipelineUpload,
  getPipelineJobs,
  PipelineJob,
} from '../services/metricsApi';
import { PageHeader } from '../components/common/PageHeader';
import { fmtDateTime } from '../utils/dateUtils';
import './PipelinePage.css';

const DB_ICONS: Record<string, string> = {
  postgres: '🐘', postgresql: '🐘', qdrant: '🧭',
  elasticsearch: '🔎', neo4j: '🕸️', redis: '⚡',
  milvus: '📡', vector: '🧮', keyword: '🔤', cache: '⚡',
};

const SERVICE_LABELS: Record<string, string> = {
  postgres: 'PostgreSQL',
  postgresql: 'PostgreSQL',
  qdrant: 'Qdrant 向量库',
  elasticsearch: 'Elasticsearch',
  neo4j: 'Neo4j 图库',
  redis: 'Redis 缓存',
  milvus: 'Milvus 向量库',
  cache: '缓存',
  vector: '向量索引',
  keyword: '全文索引',
};

const STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  ocr: '识别文字中',
  chunk: '切段中',
  embed: '编码中',
  ingest: '写入中',
  done: '完成',
  failed: '失败',
};

const STATUS_COLOR: Record<string, string> = {
  queued: '#94a3b8',
  ocr: '#3b82f6',
  chunk: '#6366f1',
  embed: '#8b5cf6',
  ingest: '#0ea5e9',
  done: '#10b981',
  failed: '#ef4444',
};

export const PipelinePage: React.FC = () => {
  const [arch, setArch] = useState<LiveArchitecture | null>(null);
  const [, setArchLoaded] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [showAllJobs, setShowAllJobs] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [jobs, setJobs] = useState<PipelineJob[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshJobs = useCallback(async () => {
    const list = await getPipelineJobs(50);
    setJobs(list);
  }, []);

  useEffect(() => {
    const fetchHealth = async () => {
      const a = await getLiveArchitecture();
      setArch(a);
      setArchLoaded(true);
    };
    fetchHealth();
    refreshJobs();
    const t1 = setInterval(fetchHealth, 15000);
    const t2 = setInterval(refreshJobs, 3000);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, [refreshJobs]);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    const r = await pipelineUpload(file);
    setUploading(false);
    if (r.ok) {
      setUploadResult({ ok: true, msg: '文件已提交，系统正在处理，请稍候…' });
      setFile(null);
      if (fileRef.current) fileRef.current.value = '';
      refreshJobs();
    } else {
      setUploadResult({ ok: false, msg: r.error || '上传失败' });
    }
  };

  const services = arch?.stores
    ? Object.entries(arch.stores).map(([k, v]) => ({
        key: k,
        label: SERVICE_LABELS[k] || k,
        status:
          v?.configured === false
            ? 'unknown'
            : v?.available
              ? 'healthy'
              : 'unhealthy',
        configured: v?.configured !== false,
      }))
    : [];

  const overall = arch
    ? arch.summary.down > 0
      ? 'down'
      : arch.summary.degraded > 0
        ? 'degraded'
        : 'ok'
    : 'unknown';

  return (
    <div className="pipeline-page">
      <PageHeader title="文档上传" subtitle="上传文件，系统自动识别、整理并写入知识库" />

      {/* DB 状态图标条 */}
      <div className="db-status-bar">
        {arch ? services.map((s) => (
          <div key={s.key}
            className={`db-chip ${!s.configured ? 'uncfg' : s.status === 'healthy' ? 'ok' : s.status === 'unhealthy' ? 'err' : 'unk'}`}
            title={`${s.label} · ${!s.configured ? '未配置' : s.status === 'healthy' ? '正常' : s.status === 'unhealthy' ? '异常' : '未知'}`}
          >
            <span>{DB_ICONS[s.key] || '🗄️'}</span>
            <span className="db-chip-dot" />
          </div>
        )) : <span className="db-loading">连接中…</span>}
        {arch && (
          <span className={`db-overall ${overall === 'ok' ? 'ok' : overall === 'degraded' ? 'warn' : 'err'}`}>
            {overall === 'ok' ? '✅ 全部正常' : overall === 'degraded' ? '⚠️ 部分异常' : '🔴 不可用'}
          </span>
        )}
      </div>

      <div className="pipeline-grid">
        <section className="pipeline-card">
          <h2>文档上传</h2>
          <div className="upload-zone" onClick={() => fileRef.current?.click()}>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.txt,.md"
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
                <span className="hint-formats">PDF · PNG · JPG · TXT · MD</span>
              </div>
            )}
          </div>

          {file && (
            <button className="upload-btn" onClick={handleUpload} disabled={uploading}>
              {uploading ? '提交中…' : '上传并处理'}
            </button>
          )}

          {uploadResult && (
            <div className={`upload-result ${uploadResult.ok ? 'success' : 'error'}`}>
              {uploadResult.msg}
            </div>
          )}
        </section>
      </div>

      <section className="pipeline-jobs">
        <div className="pipeline-jobs-head">
          <span>最近任务</span>
          {jobs.length > 3 && (
            <button className="jobs-toggle" onClick={() => setShowAllJobs(v => !v)}>
              {showAllJobs ? '收起' : `全部 ${jobs.length} 条`}
            </button>
          )}
        </div>
        {jobs.length === 0 ? (
          <p className="loading-text">暂无任务</p>
        ) : (
          <div className="job-list">
            {(showAllJobs ? jobs : jobs.slice(0, 3)).map((j) => (
              <div key={j.job_id} className="job-row">
                <span className="job-status-dot" style={{ background: STATUS_COLOR[j.status] || '#64748b' }} />
                <span className="job-name" title={j.file_name}>{j.file_name}</span>
                <span className="job-badge" style={{ background: STATUS_COLOR[j.status] || '#64748b' }}>
                  {STATUS_LABELS[j.status] || j.status}
                </span>
                {j.chunks_inserted != null && (
                  <span className="job-meta">{j.chunks_inserted} 片段</span>
                )}
                {j.duration_ms != null && (
                  <span className="job-meta">{j.duration_ms}毫秒</span>
                )}
                <span className="job-time">{fmtDateTime(j.created_at)}</span>
                {j.error && <span className="job-err" title={j.error}>⚠</span>}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};
