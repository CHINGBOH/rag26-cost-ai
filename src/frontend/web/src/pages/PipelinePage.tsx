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
import { StatusDot } from '../components/common/StatusDot';
import { fmtTime, fmtDateTime } from '../utils/dateUtils';
import './PipelinePage.css';

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
  const [archLoaded, setArchLoaded] = useState(false);
  const [file, setFile] = useState<File | null>(null);
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

      <div className="pipeline-grid">
        <section className="pipeline-card">
          <h2>各数据库状态</h2>
          {arch ? (
            <div className="health-grid">
              {services.map((s) => (
                <div key={s.key} className="health-item">
                  <StatusDot status={s.status} />
                  <span className="health-label">{s.label}</span>
                  <span className="health-status">
                    {!s.configured ? '未配置' : s.status === 'healthy' ? '正常' : s.status === 'unhealthy' ? '异常' : '未知'}
                  </span>
                </div>
              ))}
            </div>
          ) : archLoaded ? (
            <p className="loading-text">无法连接到检索服务</p>
          ) : (
            <p className="loading-text">加载中…</p>
          )}
          {arch && (
            <div className="health-footer">
              整体 <strong>
                {overall === 'ok' ? '全部正常' : overall === 'degraded' ? '部分异常' : overall === 'down' ? '不可用' : '检查中'}
              </strong>
              <span className="health-time">
                更新于 {fmtTime(arch.generated_at)}
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

      <section className="pipeline-card" style={{ marginTop: 16 }}>
        <h2>管道任务 <span style={{ color: '#94a3b8', fontSize: 13, fontWeight: 400 }}>({jobs.length})</span></h2>
        {jobs.length === 0 ? (
          <p className="loading-text">暂无任务</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: '#64748b', borderBottom: '1px solid #e2e8f0' }}>
                  <th style={{ padding: '8px 6px' }}>文件</th>
                  <th style={{ padding: '8px 6px' }}>状态</th>
                  <th style={{ padding: '8px 6px' }}>识别页数</th>
                  <th style={{ padding: '8px 6px' }}>字符数</th>
                  <th style={{ padding: '8px 6px' }}>片段数</th>
                  <th style={{ padding: '8px 6px' }}>耗时</th>
                  <th style={{ padding: '8px 6px' }}>提交</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.job_id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '6px', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={j.file_name}>{j.file_name}</td>
                    <td style={{ padding: '6px' }}>
                      <span style={{
                        background: STATUS_COLOR[j.status] || '#64748b',
                        color: '#fff', padding: '2px 8px', borderRadius: 10, fontSize: 11,
                      }}>
                        {STATUS_LABELS[j.status] || j.status}
                      </span>
                      {j.ocr_unavailable && (
                        <span style={{ marginLeft: 6, fontSize: 11, color: '#ef4444' }}>OCR未启动</span>
                      )}
                      {j.error && (
                        <span style={{ marginLeft: 6, fontSize: 11, color: '#ef4444' }} title={j.error}>
                          ⚠ {j.error.slice(0, 40)}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '6px' }}>{j.ocr_pages ?? '-'}</td>
                    <td style={{ padding: '6px' }}>{j.text_chars ?? '-'}</td>
                    <td style={{ padding: '6px' }}>{j.chunks_inserted != null ? `${j.chunks_inserted}/${j.chunks_total ?? '?'}` : '-'}</td>
                    <td style={{ padding: '6px' }}>{j.duration_ms != null ? `${j.duration_ms}毫秒` : '-'}</td>
                    <td style={{ padding: '6px', color: '#64748b' }}>{fmtDateTime(j.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
};
