"""Domain models. Plain pydantic — no Genblaze imports live here."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Format = Literal["1:1", "9:16", "16:9"]


# --------------------------------------------------------------------------
# Brand kit — the governance input
# --------------------------------------------------------------------------
class BrandKit(BaseModel):
    name: str = Field(..., description="Brand name")
    tone: str = Field("confident, warm, plain-spoken", description="Voice guidance")
    palette: list[str] = Field(default_factory=list, description="Hex colors")
    visual_rules: list[str] = Field(default_factory=list)
    banned_claims: list[str] = Field(
        default_factory=lambda: ["guaranteed", "cures", "100% safe", "risk-free"],
        description="Phrases that must never appear in copy",
    )
    required_disclosure: str = Field(
        "Contains AI-generated imagery.",
        description="Disclosure line required on delivered creative (EU AI Act Art. 50)",
    )
    reference_asset_urls: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Campaign plan — produced by the planner LLM
# --------------------------------------------------------------------------
class Scene(BaseModel):
    headline: str
    image_prompt: str
    voiceover: str = ""


class CampaignSpec(BaseModel):
    campaign_title: str
    audience: str
    scenes: list[Scene]
    disclosure_line: str = "Contains AI-generated imagery."


# --------------------------------------------------------------------------
# Judge verdict — produced by the vision + policy evaluators
# --------------------------------------------------------------------------
class Verdict(BaseModel):
    passed: bool
    score: float = 0.0
    brand_issues: list[str] = Field(default_factory=list)
    policy_issues: list[str] = Field(default_factory=list)
    feedback: str = ""

    @property
    def all_issues(self) -> list[str]:
        return self.brand_issues + self.policy_issues


# --------------------------------------------------------------------------
# API request / response
# --------------------------------------------------------------------------
class CampaignRequest(BaseModel):
    brief: str = Field(..., min_length=8, max_length=2000)
    brand: BrandKit
    scene_count: int = Field(2, ge=1, le=4)
    formats: list[Format] = Field(default_factory=lambda: ["1:1"])
    make_video: bool = True
    tenant_id: str = "demo"


class AssetOut(BaseModel):
    asset_id: str
    kind: Literal["image", "audio", "video"]
    media_type: str
    durable_url: str
    sha256: str | None = None
    fmt: str | None = None
    label: str = ""


class RunOut(BaseModel):
    run_id: str
    status: Literal["running", "succeeded", "failed"]
    created_at: datetime
    campaign_title: str = ""
    brand_name: str = ""
    tenant_id: str = "demo"

    manifest_uri: str | None = None
    canonical_hash: str | None = None
    verified: bool | None = None
    attest_uri: str | None = None
    retain_until: datetime | None = None

    iterations: int = 0
    verdict: Verdict | None = None
    cost_usd: float = 0.0
    assets: list[AssetOut] = Field(default_factory=list)
    error: str | None = None

    # Provenance lineage: every judge retry links parent -> child.
    lineage: list[str] = Field(default_factory=list)


class VerifyResult(BaseModel):
    found_manifest: bool
    verified: bool = False
    source: Literal["embedded", "sidecar", "b2-lookup", "none"] = "none"
    canonical_hash: str | None = None
    run_id: str | None = None
    pipeline: str | None = None
    created_at: datetime | None = None
    providers: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    parent_run_id: str | None = None
    asset_sha256: str | None = None
    file_sha256: str | None = None
    sha_match: bool | None = None
    disclosure: str | None = None
    message: str = ""
