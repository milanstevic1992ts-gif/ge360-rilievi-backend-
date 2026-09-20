from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class AIProviderError(RuntimeError): pass
class AIUnavailableError(AIProviderError): pass
class AIResponseError(AIProviderError): pass

@dataclass(frozen=True)
class ProviderHealth:
    reachable: bool
    detail: str | None = None

@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages:list[dict[str,Any]], *, tools:list[dict[str,Any]]|None=None, temperature:float=0.0)->LLMResponse: ...
    def tool_call(self, messages:list[dict[str,Any]], tools:list[dict[str,Any]])->LLMResponse:
        return self.chat(messages, tools=tools, temperature=0.0)
    @abstractmethod
    def structured_output(self, messages:list[dict[str,Any]], schema:type[T])->T: ...
    @abstractmethod
    def healthcheck(self)->ProviderHealth: ...

class VisionProvider(ABC):
    @abstractmethod
    def analyze(self, content:bytes, mime_type:str)->dict[str,Any]: ...
