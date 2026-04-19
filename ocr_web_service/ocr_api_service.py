#!/usr/bin/env python3
"""
OCR Web服务 - 前端UI封装
提供简单易用的REST API接口，支持一键上传处理
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import uuid
import time
import shutil
from pathlib import Path
from typing import List, Optional
import requests
import subprocess

# 配置
OCR_SERVICE_URL = "http://localhost:8001"
UPLOAD_DIR = "/tmp/ocr_uploads"
OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB

# 创建目录
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="OCR Web Service", version="1.0.0")

# 添加CORS支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 任务状态存储
_task_status = {}

class TaskStatus:
    def __init__(self, task_id: str, file_name: str):
        self.task_id = task_id
        self.file_name = file_name
        self.status = "pending"  # pending, processing, completed, failed
        self.progress = 0
        self.result_url: Optional[str] = None
        self.error_message: Optional[str] = None
        self.created_at = time.time()
        self.completed_at: Optional[float] = None

def get_file_size_mb(file_path: str) -> float:
    """获取文件大小（MB）"""
    return os.path.getsize(file_path) / (1024 * 1024)

def determine_processing_strategy(file_size_mb: float) -> str:
    """确定处理策略"""
    if file_size_mb < 50:
        return "sync"
    elif file_size_mb < 200:
        return "async"
    else:
        return "large"

def process_pdf_sync(file_path: str, file_name: str) -> dict:
    """同步处理PDF"""
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (file_name, f, 'application/pdf')}
            response = requests.post(f"{OCR_SERVICE_URL}/ocr/pdf", files=files, timeout=1800)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"OCR处理失败: HTTP {response.status_code}")
    except Exception as e:
        raise Exception(f"同步处理错误: {str(e)}")

def process_pdf_async(file_path: str, file_name: str) -> dict:
    """异步处理PDF"""
    try:
        # 启动异步任务
        with open(file_path, 'rb') as f:
            files = {'file': (file_name, f, 'application/pdf')}
            response = requests.post(f"{OCR_SERVICE_URL}/ocr/pdf/async", files=files, timeout=30)
        
        if response.status_code != 200:
            raise Exception(f"启动异步任务失败: HTTP {response.status_code}")
        
        job_data = response.json()
        job_id = job_data.get('job_id')
        
        if not job_id:
            raise Exception("未获得任务ID")
        
        # 轮询任务状态
        max_attempts = 120  # 10分钟
        for attempt in range(max_attempts):
            time.sleep(5)
            
            try:
                status_response = requests.get(f"{OCR_SERVICE_URL}/ocr/pdf/async/{job_id}", timeout=10)
                if status_response.status_code != 200:
                    continue
                
                status_data = status_response.json()
                status = status_data.get('status')
                
                if status == 'completed':
                    return status_data.get('result')
                elif status == 'failed':
                    error = status_data.get('error', '未知错误')
                    raise Exception(f"任务失败: {error}")
                    
            except Exception as e:
                if attempt < max_attempts - 1:
                    continue
                raise
        
        raise Exception("任务超时")
        
    except Exception as e:
        raise Exception(f"异步处理错误: {str(e)}")

def process_large_file(file_path: str, file_name: str) -> dict:
    """处理大文件（使用分块处理）"""
    try:
        # 这里调用大文件处理脚本
        script_path = "/home/l/rag-dashboard/process_large_files_simple.py"
        
        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="large_file_", dir=UPLOAD_DIR)
        
        # 复制文件到临时目录
        temp_file = os.path.join(temp_dir, file_name)
        shutil.copy2(file_path, temp_file)
        
        # 运行处理脚本
        result = subprocess.run(
            ['python3', script_path],
            cwd="/home/l/rag-dashboard",
            capture_output=True,
            text=True,
            timeout=3600
        )
        
        if result.returncode != 0:
            raise Exception(f"大文件处理失败: {result.stderr}")
        
        # 查找处理结果
        base_name = os.path.splitext(file_name)[0]
        result_file = os.path.join(OUTPUT_DIR, f"{base_name}_merged_ocr.json")
        
        if os.path.exists(result_file):
            with open(result_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            raise Exception("未找到处理结果")
            
    except Exception as e:
        raise Exception(f"大文件处理错误: {str(e)}")

def save_result(result: dict, file_name: str) -> tuple:
    """保存处理结果"""
    base_name = os.path.splitext(file_name)[0]
    
    # 保存JSON结果
    json_file = os.path.join(OUTPUT_DIR, f"{base_name}_ocr.json")
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # 保存文本结果
    text_file = os.path.join(OUTPUT_DIR, f"{base_name}_text.txt")
    with open(text_file, 'w', encoding='utf-8') as f:
        f.write(result.get('full_text', ''))
    
    return json_file, text_file

def process_task(task_id: str):
    """后台处理任务"""
    task = _task_status[task_id]
    
    try:
        task.status = "processing"
        task.progress = 10
        
        # 获取文件信息
        file_path = os.path.join(UPLOAD_DIR, f"{task_id}.pdf")
        file_size_mb = get_file_size_mb(file_path)
        
        task.progress = 20
        
        # 确定处理策略
        strategy = determine_processing_strategy(file_size_mb)
        print(f"任务 {task_id}: 使用 {strategy} 策略处理 {file_size_mb:.1f}MB 文件")
        
        task.progress = 30
        
        # 根据策略处理文件
        if strategy == "sync":
            result = process_pdf_sync(file_path, task.file_name)
        elif strategy == "async":
            result = process_pdf_async(file_path, task.file_name)
        else:  # large
            result = process_large_file(file_path, task.file_name)
        
        task.progress = 80
        
        # 保存结果
        json_file, text_file = save_result(result, task.file_name)
        
        # 更新任务状态
        task.status = "completed"
        task.progress = 100
        task.completed_at = time.time()
        task.result_url = f"/api/ocr/result/{task_id}"
        
        # 清理上传文件
        if os.path.exists(file_path):
            os.remove(file_path)
        
        print(f"任务 {task_id}: 处理完成")
        
    except Exception as e:
        task.status = "failed"
        task.error_message = str(e)
        task.completed_at = time.time()
        print(f"任务 {task_id}: 处理失败 - {str(e)}")

# API端点

@app.get("/")
async def root():
    """根端点"""
    return {
        "service": "OCR Web Service",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "upload": "/api/ocr/upload",
            "status": "/api/ocr/status/{task_id}",
            "result": "/api/ocr/result/{task_id}",
            "health": "/api/ocr/health"
        }
    }

@app.get("/api/ocr/health")
async def health_check():
    """健康检查"""
    try:
        response = requests.get(f"{OCR_SERVICE_URL}/health", timeout=5)
        ocr_status = response.json()
        
        return {
            "status": "ok",
            "web_service": "running",
            "ocr_service": ocr_status.get("status", "unknown"),
            "ocr_available": ocr_status.get("ocr_initialized", False),
            "tasks_running": len([t for t in _task_status.values() if t.status == "processing"])
        }
    except Exception as e:
        return {
            "status": "degraded",
            "error": str(e)
        }

@app.post("/api/ocr/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传文件并开始OCR处理"""
    
    # 验证文件类型
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="只支持PDF文件")
    
    # 生成任务ID
    task_id = str(uuid.uuid4())
    
    try:
        # 保存上传文件
        file_path = os.path.join(UPLOAD_DIR, f"{task_id}.pdf")
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE:
            os.remove(file_path)
            raise HTTPException(status_code=400, detail=f"文件太大，最大支持 {MAX_FILE_SIZE//1024//1024}MB")
        
        # 创建任务状态
        task = TaskStatus(task_id, file.filename)
        _task_status[task_id] = task
        
        # 启动后台处理
        import asyncio
        asyncio.create_task(asyncio.to_thread(process_task, task_id))
        
        return {
            "task_id": task_id,
            "file_name": file.filename,
            "file_size": file_size,
            "file_size_mb": file_size / (1024 * 1024),
            "status": "pending",
            "message": "文件上传成功，开始处理",
            "check_status_url": f"/api/ocr/status/{task_id}",
            "result_url": f"/api/ocr/result/{task_id}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        # 清理失败的文件
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")

@app.get("/api/ocr/status/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态"""
    if task_id not in _task_status:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task = _task_status[task_id]
    
    response = {
        "task_id": task.task_id,
        "file_name": task.file_name,
        "status": task.status,
        "progress": task.progress,
        "created_at": task.created_at,
        "completed_at": task.completed_at
    }
    
    if task.status == "completed":
        response["result_url"] = task.result_url
        response["message"] = "处理完成"
    elif task.status == "failed":
        response["error"] = task.error_message
        response["message"] = "处理失败"
    else:
        response["message"] = "正在处理中..."
    
    return response

@app.get("/api/ocr/result/{task_id}")
async def get_task_result(task_id: str):
    """获取处理结果"""
    if task_id not in _task_status:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task = _task_status[task_id]
    
    if task.status != "completed":
        raise HTTPException(status_code=400, detail=f"任务未完成，当前状态: {task.status}")
    
    # 查找结果文件
    base_name = os.path.splitext(task.file_name)[0]
    json_file = os.path.join(OUTPUT_DIR, f"{base_name}_ocr.json")
    text_file = os.path.join(OUTPUT_DIR, f"{base_name}_text.txt")
    
    if not os.path.exists(json_file):
        raise HTTPException(status_code=404, detail="结果文件不存在")
    
    # 读取结果
    with open(json_file, 'r', encoding='utf-8') as f:
        result = json.load(f)
    
    # 添加下载链接
    result["download_urls"] = {
        "json": f"/api/ocr/download/{task_id}/json",
        "text": f"/api/ocr/download/{task_id}/text"
    }
    
    return result

@app.get("/api/ocr/download/{task_id}/{format}")
async def download_result(task_id: str, format: str):
    """下载处理结果"""
    if task_id not in _task_status:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task = _task_status[task_id]
    
    if task.status != "completed":
        raise HTTPException(status_code=400, detail=f"任务未完成，当前状态: {task.status}")
    
    base_name = os.path.splitext(task.file_name)[0]
    
    if format == "json":
        file_path = os.path.join(OUTPUT_DIR, f"{base_name}_ocr.json")
        media_type = "application/json"
        file_name = f"{base_name}_ocr.json"
    elif format == "text":
        file_path = os.path.join(OUTPUT_DIR, f"{base_name}_text.txt")
        media_type = "text/plain"
        file_name = f"{base_name}_text.txt"
    else:
        raise HTTPException(status_code=400, detail="不支持的格式")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=file_name
    )

@app.get("/api/ocr/tasks")
async def list_tasks():
    """列出所有任务"""
    tasks = []
    for task_id, task in _task_status.items():
        tasks.append({
            "task_id": task_id,
            "file_name": task.file_name,
            "status": task.status,
            "progress": task.progress,
            "created_at": task.created_at,
            "completed_at": task.completed_at
        })
    
    return {
        "total_tasks": len(tasks),
        "tasks": sorted(tasks, key=lambda x: x["created_at"], reverse=True)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)