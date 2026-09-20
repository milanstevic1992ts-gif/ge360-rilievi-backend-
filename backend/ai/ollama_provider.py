from __future__ import annotations
import json
from typing import Any, TypeVar
import httpx
from pydantic import BaseModel, ValidationError
from .provider import AIResponseError, AIUnavailableError, LLMProvider, LLMResponse, ProviderHealth

T = TypeVar("T", bound=BaseModel)
LOCKED_MODEL = "qwen3:8b"

class OllamaProvider(LLMProvider):
    def __init__(self, base_url:str, model:str=LOCKED_MODEL, timeout_seconds:float=45.0):
        if model != LOCKED_MODEL: raise ValueError(f"GE360 AI model is locked to {LOCKED_MODEL}")
        self.base_url=base_url.rstrip("/"); self.model=LOCKED_MODEL; self.timeout_seconds=float(timeout_seconds)
    def _post(self,payload:dict[str,Any])->dict[str,Any]:
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                r=client.post(f"{self.base_url}/chat/completions",json=payload); r.raise_for_status(); body=r.json()
        except (httpx.HTTPError,ValueError) as exc:
            raise AIUnavailableError(f"Ollama unavailable: {exc}") from exc
        if not isinstance(body,dict): raise AIResponseError("Ollama returned a non-object response")
        return body
    def chat(self,messages,*,tools=None,temperature=0.0)->LLMResponse:
        payload={"model":self.model,"messages":messages,"stream":False,"temperature":temperature}
        if tools: payload.update(tools=tools,tool_choice="auto")
        body=self._post(payload)
        try: msg=body["choices"][0]["message"]
        except (KeyError,IndexError,TypeError) as exc: raise AIResponseError("Ollama response missing choices[0].message") from exc
        calls=[]
        for call in msg.get("tool_calls") or []:
            f=call.get("function") or {}; args=f.get("arguments")
            calls.append({"id":str(call.get("id") or ""),"name":str(f.get("name") or ""),"arguments":args if isinstance(args,str) else json.dumps(args or {})})
        return LLMResponse(content=msg.get("content"),tool_calls=calls,raw=body)
    def structured_output(self,messages,schema:type[T])->T:
        body=self._post({"model":self.model,"messages":messages,"stream":False,"temperature":0.0,"response_format":{"type":"json_object"}})
        try:
            return schema.model_validate(json.loads(body["choices"][0]["message"]["content"]))
        except (KeyError,IndexError,TypeError,json.JSONDecodeError,ValidationError) as exc:
            raise AIResponseError(f"Structured output failed schema validation: {exc}") from exc
    def healthcheck(self)->ProviderHealth:
        try:
            with httpx.Client(timeout=min(self.timeout_seconds,3.0)) as client:
                r=client.get(f"{self.base_url}/models"); r.raise_for_status(); body=r.json()
            models=[str(x.get("id")) for x in body.get("data",[]) if isinstance(x,dict)] if isinstance(body,dict) else []
            if models and self.model not in models: return ProviderHealth(False,f"Ollama reachable but {self.model} is not installed")
            return ProviderHealth(True,None)
        except Exception as exc: return ProviderHealth(False,str(exc))
