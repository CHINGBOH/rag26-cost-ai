"""
API 响应类型定义
"""

from typing import List, Dict, Optional, Any, TypeVar, Generic
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class APIStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"


T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    status: APIStatus
    data: Optional[T] = None
    message: Optional[str] = None
    error_code: Optional[str] = None
    request_id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S%f"))
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    @staticmethod
    def success(data: T, message: str = "OK") -> "APIResponse[T]":
        return APIResponse(status=APIStatus.SUCCESS, data=data, message=message)

    @staticmethod
    def error(message: str, error_code: str = "INTERNAL_ERROR") -> "APIResponse[Any]":
        return APIResponse(status=APIStatus.ERROR, message=message, error_code=error_code)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "message": self.message,
            "error_code": self.error_code,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        }


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    has_more: bool = False

    @property
    def total_pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "has_more": self.has_more,
        }
