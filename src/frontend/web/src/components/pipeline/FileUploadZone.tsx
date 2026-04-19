import React, { useRef, useState, useCallback } from 'react';

interface FileUploadZoneProps {
  onFilesSelected: (files: FileList) => void;
  isUploading: boolean;
  maxConcurrent: number;
  onMaxConcurrentChange: (value: number) => void;
}

export const FileUploadZone: React.FC<FileUploadZoneProps> = ({
  onFilesSelected,
  isUploading,
  maxConcurrent,
  onMaxConcurrentChange
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedCount, setSelectedCount] = useState(0);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) {
      setSelectedCount(e.dataTransfer.files.length);
      onFilesSelected(e.dataTransfer.files);
    }
  }, [onFilesSelected]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedCount(e.target.files.length);
      onFilesSelected(e.target.files);
    }
  }, [onFilesSelected]);

  return (
    <div className="file-upload-zone">
      <div className="upload-config">
        <label>并发上传数:</label>
        <select 
          value={maxConcurrent} 
          onChange={(e) => onMaxConcurrentChange(Number(e.target.value))}
          disabled={isUploading}
        >
          <option value={1}>1 (串行)</option>
          <option value={3}>3</option>
          <option value={5}>5</option>
          <option value={10}>10</option>
          <option value={20}>20</option>
        </select>
        <span className="hint">建议: 大文件选1-3，小文件选5-10</span>
      </div>

      <div
        className={`drop-zone ${isDragging ? 'dragging' : ''} ${isUploading ? 'uploading' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.txt"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />
        
        <div className="upload-icon">📁</div>
        
        {isUploading ? (
          <div className="upload-status">
            <div className="spinner" />
            <p>上传处理中...</p>
          </div>
        ) : (
          <>
            <p className="main-text">点击或拖拽文件到此处上传</p>
            <p className="sub-text">支持批量上传，最多同时处理 {maxConcurrent} 个文件</p>
            <p className="file-types">支持格式: PDF, PNG, JPG, DOC, DOCX, TXT</p>
            {selectedCount > 0 && (
              <p className="selected-info">已选择 {selectedCount} 个文件</p>
            )}
          </>
        )}
      </div>

      <div className="upload-features">
        <div className="feature">
          <span className="icon">⚡</span>
          <span>高并发处理</span>
        </div>
        <div className="feature">
          <span className="icon">🔄</span>
          <span>断点续传</span>
        </div>
        <div className="feature">
          <span className="icon">🔒</span>
          <span>安全存储</span>
        </div>
        <div className="feature">
          <span className="icon">📊</span>
          <span>实时进度</span>
        </div>
      </div>
    </div>
  );
};
