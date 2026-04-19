#!/usr/bin/env python3
"""
LLM推理服务
集成llama.cpp和vLLM，支持多种大语言模型推理
"""

import os
import asyncio
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
import json
import httpx

# 配置
LLAMA_CPP_PATH = os.getenv("LLAMA_CPP_PATH", "/usr/local/bin/llama-cli")
LLAMA_MODEL_PATH = os.getenv("LLAMA_MODEL_PATH", "/models/llama-3-8b-instruct-q4_k_m.gguf")

VLLM_API_URL = os.getenv("VLLM_API_URL", "http://localhost:8000")
VLLM_MODEL_NAME = os.getenv("VLLM_MODEL_NAME", "meta-llama/Llama-2-7b-chat-hf")

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class LLMResponse:
    """LLM响应"""
    text: str
    model: str
    tokens_used: int
    generation_time: float
    finish_reason: str
    metadata: Dict[str, Any]

@dataclass
class Message:
    """消息"""
    role: str
    content: str
    timestamp: datetime = datetime.now()

class LlamaCppService:
    """llama.cpp服务"""
    
    def __init__(self):
        self.model_path = LLAMA_MODEL_PATH
        self.llama_cli_path = LLAMA_CPP_PATH
        self.is_available = False
        
    async def initialize(self):
        """初始化llama.cpp服务"""
        logger.info("初始化llama.cpp服务...")
        
        # 检查llama.cpp是否可用
        try:
            import subprocess
            result = subprocess.run(
                [self.llama_cli_path, '--help'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                self.is_available = True
                logger.info("✓ llama.cpp服务可用")
            else:
                logger.warning("llama.cpp不可用，将使用vLLM")
                
        except Exception as e:
            logger.warning(f"无法检查llama.cpp: {e}")
    
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        repeat_penalty: float = 1.1,
        stop: Optional[List[str]] = None
    ) -> LLMResponse:
        """使用llama.cpp生成文本"""
        if not self.is_available:
            raise Exception("llama.cpp服务不可用")
        
        start_time = datetime.now()
        
        try:
            # 构建命令
            cmd = [
                self.llama_cli_path,
                '--model', self.model_path,
                '--prompt', prompt,
                '--n-predict', str(max_tokens),
                '--temperature', str(temperature),
                '--top-p', str(top_p),
                '--top-k', str(top_k),
                '--repeat-penalty', str(repeat_penalty),
                '--color',
                '--no-display-prompt'
            ]
            
            # 添加停止词
            if stop:
                for s in stop:
                    cmd.extend(['--reverse-prompt', s])
            
            # 执行命令
            import subprocess
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(timeout=120)
            
            if process.returncode != 0:
                raise Exception(f"llama.cpp执行失败: {stderr}")
            
            # 解析输出
            generated_text = stdout.strip()
            generation_time = (datetime.now() - start_time).total_seconds()
            
            # 估算token数量（粗略估算：4字符/token）
            tokens_used = len(generated_text) // 4
            
            return LLMResponse(
                text=generated_text,
                model=f"llama.cpp:{os.path.basename(self.model_path)}",
                tokens_used=tokens_used,
                generation_time=generation_time,
                finish_reason="length",
                metadata={
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k
                }
            )
            
        except subprocess.TimeoutExpired:
            process.kill()
            raise Exception("llama.cpp生成超时")
        except Exception as e:
            logger.error(f"llama.cpp生成失败: {e}")
            raise
    
    async def generate_stream(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成文本"""
        if not self.is_available:
            raise Exception("llama.cpp服务不可用")
        
        try:
            # 构建命令
            cmd = [
                self.llama_cli_path,
                '--model', self.model_path,
                '--prompt', prompt,
                '--n-predict', str(max_tokens),
                '--temperature', str(temperature),
                '--top-p', str(top_p),
                '--color',
                '--no-display-prompt'
            ]
            
            # 执行命令并流式读取输出
            import subprocess
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # 流式读取输出
            for line in process.stdout:
                yield line
            
            process.wait()
            
            if process.returncode != 0:
                stderr = process.stderr.read()
                raise Exception(f"llama.cpp流式生成失败: {stderr}")
                
        except Exception as e:
            logger.error(f"llama.cpp流式生成失败: {e}")
            raise

class VLLMService:
    """vLLM服务"""
    
    def __init__(self):
        self.api_url = VLLM_API_URL
        self.model_name = VLLM_MODEL_NAME
        self.client = None
        self.is_available = False
        
    async def initialize(self):
        """初始化vLLM服务"""
        logger.info("初始化vLLM服务...")
        
        try:
            self.client = httpx.AsyncClient(timeout=120.0)
            
            # 检查vLLM是否可用
            response = await self.client.get(f"{self.api_url}/health")
            
            if response.status_code == 200:
                self.is_available = True
                logger.info("✓ vLLM服务可用")
            else:
                logger.warning("vLLM服务不可用")
                
        except Exception as e:
            logger.warning(f"无法连接到vLLM: {e}")
    
    async def generate(
        self,
        messages: List[Message],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        stop: Optional[List[str]] = None,
        stream: bool = False
    ) -> LLMResponse:
        """使用vLLM生成文本"""
        if not self.is_available:
            raise Exception("vLLM服务不可用")
        
        start_time = datetime.now()
        
        try:
            # 构建请求
            request_data = {
                "model": self.model_name,
                "messages": [
                    {"role": msg.role, "content": msg.content}
                    for msg in messages
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stream": stream
            }
            
            if stop:
                request_data["stop"] = stop
            
            # 发送请求
            if stream:
                # 流式生成
                response = await self.client.post(
                    f"{self.api_url}/v1/chat/completions",
                    json=request_data,
                    stream=True
                )
                
                generated_text = ""
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data)
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                generated_text += content
                        except json.JSONDecodeError:
                            continue
            else:
                # 非流式生成
                response = await self.client.post(
                    f"{self.api_url}/v1/chat/completions",
                    json=request_data
                )
                
                if response.status_code != 200:
                    raise Exception(f"vLLM请求失败: {response.text}")
                
                data = response.json()
                
                if "choices" not in data or len(data["choices"]) == 0:
                    raise Exception("vLLM响应格式错误")
                
                generated_text = data["choices"][0]["message"]["content"]
            
            generation_time = (datetime.now() - start_time).total_seconds()
            
            # 提取使用信息
            usage = data.get("usage", {})
            tokens_used = usage.get("total_tokens", 0)
            finish_reason = data.get("choices", [{}])[0].get("finish_reason", "stop")
            
            return LLMResponse(
                text=generated_text,
                model=data.get("model", self.model_name),
                tokens_used=tokens_used,
                generation_time=generation_time,
                finish_reason=finish_reason,
                metadata={
                    "temperature": temperature,
                    "top_p": top_p,
                    "usage": usage
                }
            )
            
        except Exception as e:
            logger.error(f"vLLM生成失败: {e}")
            raise
    
    async def generate_stream(
        self,
        messages: List[Message],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成文本"""
        if not self.is_available:
            raise Exception("vLLM服务不可用")
        
        try:
            # 构建请求
            request_data = {
                "model": self.model_name,
                "messages": [
                    {"role": msg.role, "content": msg.content}
                    for msg in messages
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stream": True
            }
            
            # 发送流式请求
            response = await self.client.post(
                f"{self.api_url}/v1/chat/completions",
                json=request_data,
                stream=True
            )
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(data)
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
                        
        except Exception as e:
            logger.error(f"vLLM流式生成失败: {e}")
            raise
    
    async def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        if not self.is_available:
            return {}
        
        try:
            response = await self.client.get(f"{self.api_url}/v1/models")
            
            if response.status_code == 200:
                return response.json()
            
            return {}
            
        except Exception as e:
            logger.error(f"获取模型信息失败: {e}")
            return {}

class UnifiedLLMService:
    """统一LLM服务，自动选择可用的后端"""
    
    def __init__(self):
        self.llama_service = LlamaCppService()
        self.vllm_service = VLLMService()
        self.preferred_backend = "vllm"  # 优先使用vLLM
        
    async def initialize(self):
        """初始化统一LLM服务"""
        logger.info("初始化统一LLM服务...")
        
        # 初始化各个后端
        await self.llama_service.initialize()
        await self.vllm_service.initialize()
        
        # 确定可用的后端
        if self.vllm_service.is_available:
            logger.info("✓ 使用vLLM作为主要后端")
            self.preferred_backend = "vllm"
        elif self.llama_service.is_available:
            logger.info("✓ 使用llama.cpp作为主要后端")
            self.preferred_backend = "llama_cpp"
        else:
            logger.warning("⚠ 没有可用的LLM后端")
        
        logger.info("✓ 统一LLM服务初始化完成")
    
    async def generate(
        self,
        prompt_or_messages: Any,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        backend: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """生成文本"""
        # 选择后端
        backend = backend or self.preferred_backend
        
        if backend == "vllm" and self.vllm_service.is_available:
            # 转换prompt为messages格式
            if isinstance(prompt_or_messages, str):
                messages = [Message(role="user", content=prompt_or_messages)]
            else:
                messages = prompt_or_messages
            
            return await self.vllm_service.generate(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                **kwargs
            )
        
        elif backend == "llama_cpp" and self.llama_service.is_available:
            # 转换messages为prompt格式
            if isinstance(prompt_or_messages, str):
                prompt = prompt_or_messages
            else:
                prompt = self._messages_to_prompt(prompt_or_messages)
            
            return await self.llama_service.generate(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                **kwargs
            )
        
        else:
            raise Exception(f"后端 {backend} 不可用")
    
    async def generate_stream(
        self,
        prompt_or_messages: Any,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        backend: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式生成文本"""
        # 选择后端
        backend = backend or self.preferred_backend
        
        if backend == "vllm" and self.vllm_service.is_available:
            # 转换prompt为messages格式
            if isinstance(prompt_or_messages, str):
                messages = [Message(role="user", content=prompt_or_messages)]
            else:
                messages = prompt_or_messages
            
            async for chunk in self.vllm_service.generate_stream(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                **kwargs
            ):
                yield chunk
        
        elif backend == "llama_cpp" and self.llama_service.is_available:
            # 转换messages为prompt格式
            if isinstance(prompt_or_messages, str):
                prompt = prompt_or_messages
            else:
                prompt = self._messages_to_prompt(prompt_or_messages)
            
            async for chunk in self.llama_service.generate_stream(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                **kwargs
            ):
                yield chunk
        
        else:
            raise Exception(f"后端 {backend} 不可用")
    
    def _messages_to_prompt(self, messages: List[Message]) -> str:
        """将messages转换为prompt格式"""
        prompt = ""
        for message in messages:
            if message.role == "system":
                prompt += f"System: {message.content}\n\n"
            elif message.role == "user":
                prompt += f"User: {message.content}\n\n"
            elif message.role == "assistant":
                prompt += f"Assistant: {message.content}\n\n"
        
        prompt += "Assistant:"
        return prompt
    
    async def get_available_backends(self) -> List[str]:
        """获取可用的后端列表"""
        backends = []
        
        if self.vllm_service.is_available:
            backends.append("vllm")
        
        if self.llama_service.is_available:
            backends.append("llama_cpp")
        
        return backends
    
    async def close(self):
        """关闭服务"""
        logger.info("关闭统一LLM服务...")
        
        if self.vllm_service.client:
            await self.vllm_service.client.aclose()
        
        logger.info("✓ 统一LLM服务已关闭")

# 全局实例
unified_llm_service = UnifiedLLMService()

async def get_llm_service() -> UnifiedLLMService:
    """获取LLM服务实例"""
    if not unified_llm_service.vllm_service.is_available and not unified_llm_service.llama_service.is_available:
        await unified_llm_service.initialize()
    return unified_llm_service