#!/usr/bin/env python3
"""
简化LLM推理服务
基于Transformers实现，支持流式输出
专注于稳定性和可靠性
"""

import os
import sys
import asyncio
import logging
import json
import time
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ 配置 ============

MODEL_PATH = "/home/l/rag-dashboard/models"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ============ 数据模型 ============

@dataclass
class LLMRequest:
    """LLM请求"""
    prompt: str
    max_new_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    do_sample: bool = True
    stream: bool = False

@dataclass
class LLMResponse:
    """LLM响应"""
    text: str
    model: str
    tokens_generated: int
    generation_time: float
    finish_reason: str

# ============ LLM推理引擎 ============

class SimpleLLMEngine:
    """简化LLM推理引擎"""
    
    def __init__(self, model_name: str = None):
        self.model_name = model_name or "Qwen/Qwen2.5-7B-Instruct"
        self.model_path = os.path.join(MODEL_PATH, self.model_name.replace("/", "--"))
        self.device = DEVICE
        self.tokenizer = None
        self.model = None
        self.is_loaded = False
        
    async def load_model(self):
        """加载模型"""
        try:
            logger.info(f"加载模型: {self.model_name}")
            logger.info(f"设备: {self.device}")
            
            # 尝试从本地加载
            if os.path.exists(self.model_path):
                logger.info(f"从本地加载模型: {self.model_path}")
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_path,
                    torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                    device_map=self.device,
                    trust_remote_code=True
                )
            else:
                logger.info(f"从HuggingFace加载模型: {self.model_name}")
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_name,
                    trust_remote_code=True
                )
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                    device_map=self.device,
                    trust_remote_code=True
                )
            
            self.model.eval()
            self.is_loaded = True
            
            logger.info(f"✓ 模型加载成功: {self.model_name}")
            logger.info(f"✓ 设备: {self.device}")
            logger.info(f"✓ 参数量: {self.model.num_parameters() / 1e9:.2f}B")
            
        except Exception as e:
            logger.error(f"✗ 模型加载失败: {e}")
            self.is_loaded = False
            raise
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """生成文本"""
        if not self.is_loaded:
            raise RuntimeError("模型未加载")
        
        start_time = time.time()
        
        try:
            # 准备输入
            inputs = self.tokenizer(
                request.prompt,
                return_tensors="pt",
                truncation=True,
                max_length=4096
            ).to(self.device)
            
            # 生成
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=request.max_new_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    top_k=request.top_k,
                    do_sample=request.do_sample,
                    pad_token_id=self.tokenizer.eos_token_id,
                    repetition_penalty=1.1,
                    length_penalty=1.0
                )
            
            # 解码
            generated_ids = outputs[0][inputs.input_ids.shape[1]:]
            generated_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
            
            generation_time = time.time() - start_time
            
            return LLMResponse(
                text=generated_text,
                model=self.model_name,
                tokens_generated=len(generated_ids),
                generation_time=generation_time,
                finish_reason="stop"
            )
            
        except Exception as e:
            logger.error(f"生成失败: {e}")
            raise
    
    async def generate_stream(self, request: LLMRequest) -> AsyncGenerator[str, None]:
        """流式生成文本"""
        if not self.is_loaded:
            raise RuntimeError("模型未加载")
        
        try:
            # 准备输入
            inputs = self.tokenizer(
                request.prompt,
                return_tensors="pt",
                truncation=True,
                max_length=4096
            ).to(self.device)
            
            # 生成
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=request.max_new_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    top_k=request.top_k,
                    do_sample=request.do_sample,
                    pad_token_id=self.tokenizer.eos_token_id,
                    repetition_penalty=1.1,
                    length_penalty=1.0,
                    output_scores=True,
                    return_dict_in_generate=True
                )
            
            # 流式解码
            for output in outputs:
                generated_ids = output[0][inputs.input_ids.shape[1]:]
                chunk = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
                if chunk:
                    yield chunk
                await asyncio.sleep(0.01)  # 模拟流式延迟
            
        except Exception as e:
            logger.error(f"流式生成失败: {e}")
            raise
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "status": "healthy" if self.is_loaded else "unhealthy",
            "model": self.model_name,
            "device": self.device,
            "is_loaded": self.is_loaded,
            "parameters": self.model.num_parameters() / 1e9 if self.is_loaded else 0
        }

# ============ FastAPI服务 ============

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI(title="简化LLM推理服务", version="1.0.0")

llm_engine = SimpleLLMEngine()

@app.on_event("startup")
async def startup_event():
    try:
        await llm_engine.load_model()
    except Exception as e:
        logger.error(f"启动失败: {e}")

@app.get("/health")
async def health_check():
    return llm_engine.health_check()

@app.post("/api/generate")
async def generate_text(request: dict):
    """生成文本"""
    try:
        llm_request = LLMRequest(
            prompt=request['prompt'],
            max_new_tokens=request.get('max_tokens', 512),
            temperature=request.get('temperature', 0.7),
            top_p=request.get('top_p', 0.9),
            top_k=request.get('top_k', 40),
            do_sample=request.get('do_sample', True),
            stream=request.get('stream', False)
        )
        
        if llm_request.stream:
            async def generate():
                async for chunk in llm_engine.generate_stream(llm_request):
                    yield chunk
            
            return StreamingResponse(generate(), media_type="text/plain")
        else:
            response = await llm_engine.generate(llm_request)
            return {
                "text": response.text,
                "model": response.model,
                "tokens_generated": response.tokens_generated,
                "generation_time": response.generation_time,
                "finish_reason": response.finish_reason
            }
            
    except Exception as e:
        logger.error(f"生成文本失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat_completion(request: dict):
    """聊天完成（兼容格式）"""
    try:
        # 构建对话提示
        messages = request.get('messages', [])
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        # 简单的消息格式化
        prompt = ""
        for msg in messages:
            if msg['role'] == 'system':
                prompt += f"系统: {msg['content']}\n"
            elif msg['role'] == 'user':
                prompt += f"用户: {msg['content']}\n"
            elif msg['role'] == 'assistant':
                prompt += f"助手: {msg['content']}\n"
        
        prompt += "助手: "
        
        llm_request = LLMRequest(
            prompt=prompt,
            max_new_tokens=request.get('max_tokens', 512),
            temperature=request.get('temperature', 0.7),
            top_p=request.get('top_p', 0.9),
            top_k=request.get('top_k', 40),
            do_sample=request.get('do_sample', True),
            stream=request.get('stream', False)
        )
        
        if request.get('stream', False):
            async def generate():
                async for chunk in llm_engine.generate_stream(llm_request):
                    yield chunk
            
            return StreamingResponse(generate(), media_type="text/plain")
        else:
            response = await llm_engine.generate(llm_request)
            
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": response.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response.text
                    },
                    "finish_reason": response.finish_reason
                }],
                "usage": {
                    "prompt_tokens": len(prompt.split()),
                    "completion_tokens": response.tokens_generated,
                    "total_tokens": len(prompt.split()) + response.tokens_generated
                }
            }
            
    except Exception as e:
        logger.error(f"聊天完成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)