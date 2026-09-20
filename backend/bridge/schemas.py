from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CreateBridgeDeviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)


class BridgeDeviceResponse(BaseModel):
    device_id: str
    name: str
    vpn_ip: str
    public_key: str
    created_at: str
    last_seen_at: str | None = None
    status: str
    revoked_at: str | None = None
    last_handshake_at: str | None = None
    rx_bytes: int = 0
    tx_bytes: int = 0
