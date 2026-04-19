import React, { useState, useRef } from 'react';
import { uploadDocument } from '../services/ragApi';

export const UploadPanel: React.FC = () => {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<any>(null);
  const [error, setError] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      setError('');
      setUploadResult(null);
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setError('请选择文件');
      return;
    }

    setUploading(true);
    setError('');
    
    try {
      const result = await uploadDocument(file);
      setUploadResult(result);
      setFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (err: any) {
      setError(err.message || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ padding: '20px', maxWidth: '600px', margin: '0 auto' }}>
      <h2>📄 文档上传</h2>
      
      <div
        style={{
          border: '2px dashed #ccc',
          borderRadius: '8px',
          padding: '40px',
          textAlign: 'center',
          marginBottom: '20px',
          backgroundColor: '#fafafa'
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />
        
        <button
          onClick={() => fileInputRef.current?.click()}
          style={{
            padding: '10px 20px',
            fontSize: '16px',
            backgroundColor: '#52c41a',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            marginBottom: '10px'
          }}
        >
          选择文件
        </button>
        
        {file && (
          <div style={{ marginTop: '10px', color: '#333' }}>
            已选择: <strong>{file.name}</strong> ({(file.size / 1024).toFixed(2)} KB)
          </div>
        )}
        
        <div style={{ marginTop: '10px', color: '#999', fontSize: '14px' }}>
          支持格式: PDF, PNG, JPG
        </div>
      </div>

      {file && (
        <button
          onClick={handleUpload}
          disabled={uploading}
          style={{
            width: '100%',
            padding: '12px',
            fontSize: '16px',
            backgroundColor: '#1890ff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: uploading ? 'not-allowed' : 'pointer'
          }}
        >
          {uploading ? '上传处理中...' : '开始上传'}
        </button>
      )}

      {error && (
        <div style={{ marginTop: '15px', padding: '10px', backgroundColor: '#fff2f0', color: '#ff4d4f', borderRadius: '4px' }}>
          ❌ {error}
        </div>
      )}

      {uploadResult && (
        <div style={{ marginTop: '15px', padding: '15px', backgroundColor: '#f6ffed', color: '#52c41a', borderRadius: '4px' }}>
          <div>✅ 上传成功!</div>
          <div style={{ marginTop: '5px', fontSize: '14px' }}>
            文档ID: {uploadResult.doc_id}<br/>
            状态: {uploadResult.status}
          </div>
        </div>
      )}
    </div>
  );
};
