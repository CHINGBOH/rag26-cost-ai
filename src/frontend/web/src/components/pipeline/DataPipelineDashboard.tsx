/**
 * 数据管道全面看板
 * 包含：OCR上传、四库状态、Embedding/Rerank评估、数据流监控
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useWebSocket } from '../../hooks/useWebSocket';
import { FileUploadZone } from './FileUploadZone';
import { PipelineMetrics } from './PipelineMetrics';
import { DatabaseStatusPanel } from './DatabaseStatusPanel';
import { ProcessingQueue } from './ProcessingQueue';
import { EvaluationPanel } from './EvaluationPanel';
import { DataFlowVisualization } from './DataFlowVisualization';
import './DataPipelineDashboard.css';
import { authFetch } from '../../utils/auth';
import type { UploadFile, PipelineStats, DatabaseHealth, EvaluationMetrics } from './types';

export const DataPipelineDashboard: React.FC = () => {
  const { isConnected, subscribe } = useWebSocket();
  const [activeTab, setActiveTab] = useState<'upload' | 'status' | 'evaluation' | 'flow'>('upload');
  const [uploadQueue, setUploadQueue] = useState<UploadFile[]>([]);
  const [pipelineStats, setPipelineStats] = useState<PipelineStats>({
    totalFiles: 0,
    completedFiles: 0,
    failedFiles: 0,
    processingFiles: 0,
    averageProcessingTime: 0,
    queueLength: 0,
    throughput: 0
  });
  const [dbHealth, setDbHealth] = useState<DatabaseHealth>({
    vector: { status: 'healthy', latency: 0, count: 0 },
    keyword: { status: 'healthy', latency: 0, count: 0 },
    graph: { status: 'healthy', latency: 0, count: 0 },
    cache: { status: 'healthy', latency: 0, count: 0 }
  });
  const [evalMetrics, setEvalMetrics] = useState<EvaluationMetrics>({
    embedding: { averageTime: 0, successRate: 100, queueSize: 0, batchSize: 32 },
    rerank: { averageTime: 0, successRate: 100, crossEncoderLatency: 0, fusionScoreAccuracy: 0 }
  });
  const [isUploading, setIsUploading] = useState(false);
  const [maxConcurrent, setMaxConcurrent] = useState(5);

  useEffect(() => {
    const unsubscribe = subscribe((event: any) => {
      if (event.type === 'ocr:progress') {
        updateFileProgress(event.payload);
      } else if (event.type === 'pipeline:stats') {
        setPipelineStats(event.payload);
      } else if (event.type === 'database:health') {
        setDbHealth(event.payload);
      } else if (event.type === 'evaluation:metrics') {
        setEvalMetrics(event.payload);
      }
    });
    return () => { unsubscribe(); };
  }, [subscribe]);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const healthRes = await authFetch('/api/pipeline/health');
        if (healthRes.ok) {
          const healthData = await healthRes.json();
          if (healthData.success) setDbHealth(healthData.data);
        }

        const statsRes = await authFetch('/api/pipeline/stats');
        if (statsRes.ok) {
          const statsData = await statsRes.json();
          if (statsData.success) setPipelineStats(statsData.data);
        }

        const evalRes = await authFetch('/api/pipeline/evaluation');
        if (evalRes.ok) {
          const evalData = await evalRes.json();
          if (evalData.success) setEvalMetrics(evalData.data);
        }
      } catch (err) {
        console.error('Failed to fetch pipeline status:', err);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const updateFileProgress = useCallback((payload: { fileId: string; progress: number; stage?: string; status?: string; error?: string }) => {
    setUploadQueue(prev => prev.map(f => {
      if (f.id === payload.fileId) {
        return {
          ...f,
          progress: payload.progress ?? f.progress,
          stage: payload.stage ?? f.stage,
          status: (payload.status as any) ?? f.status,
          error: payload.error ?? f.error,
          endTime: payload.status === 'completed' || payload.status === 'failed' ? Date.now() : f.endTime
        };
      }
      return f;
    }));
  }, []);

  const handleFilesSelected = useCallback(async (files: FileList) => {
    const newFiles: UploadFile[] = Array.from(files).map(file => ({
      id: `file_${Date.now()}_${crypto.randomUUID().slice(0, 9)}`,
      file,
      name: file.name,
      size: file.size,
      status: 'pending',
      progress: 0,
      startTime: Date.now()
    }));

    setUploadQueue(prev => [...prev, ...newFiles]);
    setIsUploading(true);
    await processUploads(newFiles);
  }, [maxConcurrent]);

  const processUploads = async (files: UploadFile[]) => {
    const pendingFiles = files.filter(f => f.status === 'pending');
    for (let i = 0; i < pendingFiles.length; i += maxConcurrent) {
      const batch = pendingFiles.slice(i, i + maxConcurrent);
      await Promise.all(batch.map(file => uploadSingleFile(file)));
    }
    setIsUploading(false);
  };

  const uploadSingleFile = async (fileInfo: UploadFile) => {
    setUploadQueue(prev => prev.map(f =>
      f.id === fileInfo.id ? { ...f, status: 'uploading', progress: 5, stage: '上传中' } : f
    ));

    const formData = new FormData();
    formData.append('file', fileInfo.file);

    try {
      const response = await authFetch('/api/v1/pipeline/upload', {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) throw new Error(`Upload failed: ${response.statusText}`);
      const result = await response.json();
      if (!result.ok || !result.job_id) {
        throw new Error(result.error || 'upload rejected');
      }
      const jobId: string = result.job_id;

      setUploadQueue(prev => prev.map(f =>
        f.id === fileInfo.id ? { ...f, status: 'processing', progress: 10, stage: '排队', jobId } : f
      ));

      // poll job status until done/failed (max ~5 min)
      const phaseLabel: Record<string, string> = {
        queued: '排队', extract: '提取', chunk: '切片',
        embed: '向量化', index: '入库', done: '完成', error: '失败',
      };
      const start = Date.now();
      while (Date.now() - start < 5 * 60_000) {
        await new Promise(r => setTimeout(r, 1500));
        const jr = await authFetch(`/api/v1/pipeline/job/${jobId}`);
        if (!jr.ok) continue;
        const j = await jr.json();
        const stage = phaseLabel[j.phase] || j.phase || j.status;
        const progress = j.progress_pct ?? 50;

        if (j.status === 'done') {
          const blindspotCount = (j.blindspots || []).length;
          const blindspotLabel = blindspotCount > 0 ? ` · ⚠️ ${blindspotCount}处图表盲洞` : '';
          // Phase J: cross-DB audit so the dashboard tells the truth about persistence.
          let auditLabel = '';
          let auditOk = true;
          try {
            const ar = await authFetch(`/api/v1/pipeline/audit/${jobId}`);
            if (ar.ok) {
              const a = await ar.json();
              auditOk = !!a.ok;
              const c = a.counts || {};
              auditLabel = auditOk
                ? ` · ✅ pg=${c.pg_text_chunks} qd=${c.qdrant_points} neo=${c.neo4j_chunks}`
                : ` · ❌ DB漂移: pg=${c.pg_text_chunks}/qd=${c.qdrant_points}/neo=${c.neo4j_chunks}`;
            }
          } catch (e) { /* audit best-effort */ }
          setUploadQueue(prev => prev.map(f =>
            f.id === fileInfo.id ? {
              ...f, status: auditOk ? 'completed' : 'failed', progress: 100,
              stage: `完成 · ${j.chunks_pg ?? 0} chunks · ${j.extractor || '?'}${blindspotLabel}${auditLabel}`,
              error: auditOk ? undefined : '三库一致性校验失败',
              result: j, endTime: Date.now(),
            } : f
          ));
          return;
        }
        if (j.status === 'failed') {
          throw new Error(j.error || 'pipeline failed');
        }
        setUploadQueue(prev => prev.map(f =>
          f.id === fileInfo.id ? { ...f, status: 'processing', progress, stage } : f
        ));
      }
      throw new Error('pipeline timeout (>5min)');
    } catch (error: any) {
      setUploadQueue(prev => prev.map(f =>
        f.id === fileInfo.id ? { ...f, status: 'failed', error: error.message, endTime: Date.now() } : f
      ));
    }
  };

  const handleRemoveFile = useCallback((fileId: string) => {
    setUploadQueue(prev => prev.filter(f => f.id !== fileId));
  }, []);

  const handleClearCompleted = useCallback(() => {
    setUploadQueue(prev => prev.filter(f => f.status !== 'completed'));
  }, []);

  const handleRetry = useCallback(async (fileId: string) => {
    const file = uploadQueue.find(f => f.id === fileId);
    if (file) {
      setUploadQueue(prev => prev.map(f => 
        f.id === fileId ? { ...f, status: 'pending', progress: 0, error: undefined } : f
      ));
      await uploadSingleFile(file);
    }
  }, [uploadQueue]);

  return (
    <div className="data-pipeline-dashboard">
      <header className="dashboard-header">
        <h1>📊 数据管道中心</h1>
        <div className="connection-status">
          <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`} />
          {isConnected ? '实时连接' : '离线'}
        </div>
      </header>

      <nav className="dashboard-tabs">
        <button className={activeTab === 'upload' ? 'active' : ''} onClick={() => setActiveTab('upload')}>
          📤 批量上传
          {uploadQueue.filter(f => f.status === 'processing' || f.status === 'uploading').length > 0 && (
            <span className="badge processing">
              {uploadQueue.filter(f => f.status === 'processing' || f.status === 'uploading').length}
            </span>
          )}
        </button>
        <button className={activeTab === 'status' ? 'active' : ''} onClick={() => setActiveTab('status')}>🗄️ 四库状态</button>
        <button className={activeTab === 'evaluation' ? 'active' : ''} onClick={() => setActiveTab('evaluation')}>📈 模型评估</button>
        <button className={activeTab === 'flow' ? 'active' : ''} onClick={() => setActiveTab('flow')}>🌊 数据流</button>
      </nav>

      <main className="dashboard-content">
        {activeTab === 'upload' && (
          <div className="upload-section">
            <FileUploadZone 
              onFilesSelected={handleFilesSelected}
              isUploading={isUploading}
              maxConcurrent={maxConcurrent}
              onMaxConcurrentChange={setMaxConcurrent}
            />
            <ProcessingQueue 
              queue={uploadQueue}
              onRemove={handleRemoveFile}
              onClearCompleted={handleClearCompleted}
              onRetry={handleRetry}
              stats={pipelineStats}
            />
          </div>
        )}
        {activeTab === 'status' && <DatabaseStatusPanel health={dbHealth} />}
        {activeTab === 'evaluation' && <EvaluationPanel metrics={evalMetrics} />}
        {activeTab === 'flow' && <DataFlowVisualization stats={pipelineStats} dbHealth={dbHealth} />}
      </main>

      <PipelineMetrics stats={pipelineStats} />
    </div>
  );
};
