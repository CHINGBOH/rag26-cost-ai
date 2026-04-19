#!/usr/bin/env python3
"""
专业LLM推理服务
支持多种推理引擎：vLLM、llama.cpp、Transformers
基于业界最佳实践实现
"""

import os
import sys
import asyncio
import logging
import json
from typing import List, Dict, Any, Optional, AsyncGenerator, Union
from dataclasses import dataclass, field
from enum import Enum
import time
from contextlib import asynccontextmanager

import httpx
from pydantic import BaseModel, Field

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ 配置 ============

class LLMEngine(Enum):
    """LLM推理引擎类型"""
    VLLM = "vllm"
    LLAMA_CPP = "llama_cpp"
    TRANSFORMERS = "transformers"
    OPENAI = "openai"

@dataclass
class LLMRequest:
    """LLM请求"""
    prompt: str
    max_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    stop: Optional[List[str]] = None
    stream: bool = True

@dataclass
class LLMResponse:
    """LLM响应"""
    text: str
    model: str
    tokens_used: int
    generation_time: float
    finish_reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

# ============ vLLM推理引擎 ============

class VLLMEngine:
    """vLLM推理引擎 - 高性能GPU推理"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.model_name = None
        self.available = False
        
    async def initialize(self):
        """初始化vLLM引擎"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 检查vLLM服务状态
                response = await client.get(f"{self.base_url}/health")
                if response.status_code == 200:
                    self.available = True
                    # 获取模型信息
                    models_response = await client.get(f"{self.base_url}/v1/models")
                    if models_response.status_code == 200:
                        models_data = models_response.json()
                        if models_data.get("data"):
                            self.model_name = models_data["data"][0]["id"]
                    
                    logger.info(f"✓ vLLM引擎可用，模型: {self.model_name}")
                else:
                    logger.warning("vLLM服务不可用")
                    self.available = False
                    
        except Exception as e:
            logger.warning(f"vLLM引擎初始化失败: {e}")
            self.available = False
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """生成文本"""
        if not self.available:
            raise RuntimeError("vLLM引擎不可用")
        
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                if request.stream:
                    # 流式生成
                    full_text = ""
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/v1/completions",
                        json={
                            "model": self.model_name,
                            "prompt": request.prompt,
                            "max_tokens": request.max_tokens,
                            "temperature": request.temperature,
                            "top_p": request.top_p,
                            "stream": True
                        }
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if line.strip().startswith("data: "):
                                data_str = line.strip()[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    if "choices" in data and data["choices"]:
                                        delta = data["choices"][0].get("text", "")
                                        full_text += delta
                                except json.JSONDecodeError:
                                    pass
                    
                    generation_time = time.time() - start_time
                    
                    return LLMResponse(
                        text=full_text,
                        model=self.model_name,
                        tokens_used=len(full_text.split()),
                        generation_time=generation_time,
                        finish_reason="stop",
                        metadata={"engine": "vllm", "stream": True}
                    )
                else:
                    # 非流式生成
                    response = await client.post(
                        f"{self.base_url}/v1/completions",
                        json={
                            "model": self.model_name,
                            "prompt": request.prompt,
                            "max_tokens": request.max_tokens,
                            "temperature": request.temperature,
                            "top_p": request.top_p,
                            "stream": False
                        }
                    )
                    response.raise_for_status()
                    
                    data = response.json()
                    generation_time = time.time() - start_time
                    
                    return LLMResponse(
                        text=data["choices"][0]["text"],
                        model=self.model_name,
                        tokens_used=data.get("usage", {}).get("total_tokens", 0),
                        generation_time=generation_time,
                        finish_reason=data["choices"][0].get("finish_reason", "stop"),
                        metadata={"engine": "vllm", "stream": False}
                    )
                    
        except Exception as e:
            logger.error(f"vLLM生成失败: {e}")
            raise

    async def generate_stream(self, request: LLMRequest) -> AsyncGenerator[str, None]:
        """流式生成文本"""
        if not self.available:
            raise RuntimeError("vLLM引擎不可用")
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/completions",
                    json={
                        "model": self.model_name,
                        "prompt": request.prompt,
                        "max_tokens": request.max_tokens,
                        "temperature": request.temperature,
                        "top_p": request.top_p,
                        "stream": True
                    }
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip().startswith("data: "):
                            data_str = line.strip()[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                if "choices" in data and data["choices"]:
                                    delta = data["choices"][0].get("text", "")
                                    if delta:
                                        yield delta
                            except json.JSONDecodeError:
                                pass
                                
        except Exception as e:
            logger.error(f"vLLM流式生成失败: {e}")
            raise

# ============ llama.cpp推理引擎 ============

class LlamaCppEngine:
    """llama.cpp推理引擎 - CPU高效推理"""
    
    def __init__(self, executable_path: str = None, model_path: str = None):
        self.executable_path = executable_path or os.getenv("LLAMA_CPP_PATH", "llama-cli")
        self.model_path = model_path or os.getenv("LLAMA_MODEL_PATH", "/models/llama-3-8b-instruct-q4_k_m.gguf")
        self.available = False
        
    async def initialize(self):
        """初始化llama.cpp引擎"""
        try:
            import subprocess
            
            # 检查llama.cpp是否可用
            result = subprocess.run(
                [self.executable_path, "--help"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                self.available = True
                logger.info(f"✓ llama.cpp引擎可用，模型: {self.model_path}")
            else:
                logger.warning("llama.cpp不可用")
                
        except Exception as e:
            logger.warning(f"llama.cpp引擎初始化失败: {e}")
            self.available = False
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """生成文本"""
        if not self.available:
            raise RuntimeError("llama.cpp引擎不可用")
        
        start_time = time.time()
        
        try:
            import subprocess
            
            # 构建命令
            cmd = [
                self.executable_path,
                '--model', self.model_path,
                '--prompt', request.prompt,
                '--n-predict', str(request.max_tokens),
                '--temperature', str(request.temperature),
                '--top-p', str(request.top_p),
                '--top-k', str(request.top_k),
                '--ctx-size', '4096',
                '--batch-size', '512',
                '--threads', '4'
            ]
            
            if request.stop:
                for stop_token in request.stop:
                    cmd.extend(['--stop', stop_token])
            
            # 执行命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            generation_time = time.time() - start_time
            
            if result.returncode == 0:
                # 提取生成的文本（llama.cpp输出包含原始prompt）
                output = result.stdout
                if request.prompt in output:
                    generated_text = output.split(request.prompt)[-1].strip()
                else:
                    generated_text = output.strip()
                
                return LLMResponse(
                    text=generated_text,
                    model=self.model_path,
                    tokens_used=len(generated_text.split()),
                    generation_time=generation_time,
                    finish_reason="stop",
                    metadata={"engine": "llama_cpp"}
                )
            else:
                raise RuntimeError(f"llama.cpp执行失败: {result.stderr}")
                
        except Exception as e:
            logger.error(f"llama.cpp生成失败: {e}")
            raise

# ============ Transformers推理引擎 ============

class TransformersEngine:
    """Transformers推理引擎 - 通用推理"""
    
    def __init__(self, model_name: str = "meta-llama/Llama-2-7b-chat-hf", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.tokenizer = None
        self.available = False
        
    async def initialize(self):
        """初始化Transformers引擎"""
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import torch
            
            logger.info(f"加载Transformers模型: {self.model_name}")
            
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
            self.available = True
            
            logger.info(f"✓ Transformers引擎可用，模型: {self.model_name}, 设备: {self.device}")
            
        except Exception as e:
            logger.warning(f"Transformers引擎初始化失败: {e}")
            self.available = False
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """生成文本"""
        if not self.available:
            raise RuntimeError("Transformers引擎不可用")
        
        start_time = time.time()
        
        try:
            # Tokenize
            inputs = self.tokenizer(
                request.prompt,
                return_tensors="pt",
                truncation=True,
                max_length=4096
            ).to(self.device)
            
            # Generate
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=request.max_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    top_k=request.top_k,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id
                )
            
            # Decode
            generated_ids = outputs[0][inputs.input_ids.shape[1]:]
            generated_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
            
            generation_time = time.time() - start_time
            
            return LLMResponse(
                text=generated_text,
                model=self.model_name,
                tokens_used=len(generated_ids),
                generation_time=generation_time,
                finish_reason="stop",
                metadata={"engine": "transformers", "device": self.device}
            )
            
        except Exception as e:
            logger.error(f"Transformers生成失败: {e}")
            raise

# ============ OpenAI API引擎 ============

class OpenAIEngine:
    """OpenAI兼容API引擎 - 支持DeepSeek等兼容API"""

    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model_name = model or os.getenv("LLM_MODEL", "deepseek-chat")
        self.available = False

    async def initialize(self):
        """初始化OpenAI引擎"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                if response.status_code == 200:
                    self.available = True
                    logger.info(f"✓ OpenAI引擎可用，API: {self.base_url}, 模型: {self.model_name}")
                else:
                    logger.warning(f"OpenAI引擎不可用: {response.status_code}")
                    self.available = False
        except Exception as e:
            logger.warning(f"OpenAI引擎初始化失败: {e}")
            self.available = False

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """生成文本"""
        if not self.available:
            raise RuntimeError("OpenAI引擎不可用")

        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                if request.stream:
                    full_text = ""
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.model_name,
                            "messages": [{"role": "user", "content": request.prompt}],
                            "max_tokens": request.max_tokens,
                            "temperature": request.temperature,
                            "top_p": request.top_p,
                            "stream": True
                        }
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if line.strip().startswith("data: "):
                                data_str = line.strip()[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    if "choices" in data and data["choices"]:
                                        delta = data["choices"][0].get("delta", {}).get("content", "")
                                        full_text += delta
                                except json.JSONDecodeError:
                                    pass

                    generation_time = time.time() - start_time

                    return LLMResponse(
                        text=full_text,
                        model=self.model_name,
                        tokens_used=len(full_text.split()),
                        generation_time=generation_time,
                        finish_reason="stop",
                        metadata={"engine": "openai", "stream": True}
                    )
                else:
                    response = await client.post(
                        f"{self.base_url}/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.model_name,
                            "messages": [{"role": "user", "content": request.prompt}],
                            "max_tokens": request.max_tokens,
                            "temperature": request.temperature,
                            "top_p": request.top_p,
                            "stream": False
                        }
                    )
                    response.raise_for_status()
                    data = response.json()

                    generation_time = time.time() - start_time
                    full_text = data["choices"][0]["message"]["content"]

                    return LLMResponse(
                        text=full_text,
                        model=self.model_name,
                        tokens_used=data.get("usage", {}).get("completion_tokens", len(full_text.split())),
                        generation_time=generation_time,
                        finish_reason=data["choices"][0].get("finish_reason", "stop"),
                        metadata={"engine": "openai", "stream": False}
                    )

        except Exception as e:
            logger.error(f"OpenAI生成失败: {e}")
            raise

# ============ 统一LLM服务 ============

class UnifiedLLMService:
    """统一LLM服务 - 自动选择最佳引擎"""

    def __init__(self):
        self.engines = {
            LLMEngine.VLLM: VLLMEngine(),
            LLMEngine.LLAMA_CPP: LlamaCppEngine(),
            LLMEngine.TRANSFORMERS: TransformersEngine(),
            LLMEngine.OPENAI: OpenAIEngine()
        }
        self.active_engine = None
        self.fallback_order = [
            LLMEngine.OPENAI,
            LLMEngine.VLLM,
            LLMEngine.LLAMA_CPP,
            LLMEngine.TRANSFORMERS
        ]
        
    async def initialize(self):
        """初始化所有引擎"""
        logger.info("初始化LLM服务...")
        
        for engine_type, engine in self.engines.items():
            await engine.initialize()
            
            # 选择第一个可用的引擎
            if not self.active_engine and engine.available:
                self.active_engine = engine_type
                logger.info(f"✓ 选择 {engine_type.value} 作为主要引擎")
        
        if not self.active_engine:
            logger.error("✗ 没有可用的LLM引擎")
            raise RuntimeError("没有可用的LLM引擎")
        
        logger.info("✓ LLM服务初始化完成")
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """生成文本（自动选择引擎）"""
        # 尝试主要引擎
        try:
            engine = self.engines[self.active_engine]
            return await engine.generate(request)
        except Exception as e:
            logger.warning(f"主要引擎 {self.active_engine.value} 失败，尝试备用引擎: {e}")
            
            # 尝试备用引擎
            for engine_type in self.fallback_order:
                if engine_type == self.active_engine:
                    continue
                
                engine = self.engines[engine_type]
                if engine.available:
                    try:
                        logger.info(f"切换到备用引擎: {engine_type.value}")
                        self.active_engine = engine_type
                        return await engine.generate(request)
                    except Exception as e:
                        logger.warning(f"备用引擎 {engine_type.value} 也失败: {e}")
            
            raise RuntimeError("所有LLM引擎都不可用")
    
    async def generate_stream(self, request: LLMRequest) -> AsyncGenerator[str, None]:
        """流式生成文本"""
        # 优先使用支持流式的引擎
        if self.active_engine == LLMEngine.VLLM:
            engine = self.engines[LLMEngine.VLLM]
            async for chunk in engine.generate_stream(request):
                yield chunk
        else:
            # 对于不支持流式的引擎，先生成完整文本，然后模拟流式输出
            response = await self.generate(request)
            for char in response.text:
                yield char
                await asyncio.sleep(0.01)  # 模拟流式延迟
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "active_engine": self.active_engine.value if self.active_engine else None,
            "engines": {
                engine_type.value: {
                    "available": engine.available,
                    "model": getattr(engine, 'model_name', None) or getattr(engine, 'model_path', None)
                }
                for engine_type, engine in self.engines.items()
            }
        }

# ============ FastAPI服务 ============

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="LLM推理服务", version="1.0.0")

llm_service = UnifiedLLMService()

class GenerationRequest(BaseModel):
    prompt: str
    max_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    stop: Optional[List[str]] = None
    stream: bool = False

class GenerationResponse(BaseModel):
    text: str
    model: str
    tokens_used: int
    generation_time: float
    finish_reason: str
    metadata: Dict[str, Any]

@app.on_event("startup")
async def startup_event():
    await llm_service.initialize()

@app.get("/health")
async def health_check():
    return await llm_service.health_check()

@app.post("/v1/completions", response_model=GenerationResponse)
async def generate_completion(request: GenerationRequest):
    """生成文本（兼容OpenAI API格式）"""
    llm_request = LLMRequest(
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        top_k=request.top_k,
        stop=request.stop,
        stream=request.stream
    )
    
    if request.stream:
        # 流式响应
        from fastapi.responses import StreamingResponse
        
        async def generate():
            llm_request.stream = True
            async for chunk in llm_service.generate_stream(llm_request):
                yield f"data: {json.dumps({'choices': [{'text': chunk}]})}\n"
            yield "data: [DONE]\n"
        
        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        # 非流式响应
        response = await llm_service.generate(llm_request)
        return GenerationResponse(
            text=response.text,
            model=response.model,
            tokens_used=response.tokens_used,
            generation_time=response.generation_time,
            finish_reason=response.finish_reason,
            metadata=response.metadata
        )

@app.post("/api/generate")
async def generate_text(request: GenerationRequest):
    """生成文本（简化API）"""
    llm_request = LLMRequest(
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        top_k=request.top_k,
        stop=request.stop,
        stream=request.stream
    )
    
    if request.stream:
        async def generate():
            async for chunk in llm_service.generate_stream(llm_request):
                yield chunk
        
        return StreamingResponse(generate(), media_type="text/plain")
    else:
        response = await llm_service.generate(llm_request)
        return {
            "text": response.text,
            "model": response.model,
            "tokens_used": response.tokens_used,
            "generation_time": response.generation_time,
            "finish_reason": response.finish_reason
        }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)