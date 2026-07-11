"""Load experiment + NIM config from YAML and environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def load_dotenv_files() -> None:
    load_dotenv(ROOT / ".env")


def load_yaml(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {p}")
    return data


def experiment_config(path: str | Path = "config/experiment_v0.prereg.yaml") -> dict[str, Any]:
    load_dotenv_files()
    return load_yaml(path)


def nim_config(path: str | Path = "config/nim.pinned.yaml") -> dict[str, Any]:
    load_dotenv_files()
    cfg = load_yaml(path)
    # Env overrides for model pins / key
    cfg["api_key"] = os.getenv("NVIDIA_API_KEY", "")
    cfg["base_url"] = os.getenv("NIM_BASE_URL", cfg.get("base_url", "https://integrate.api.nvidia.com/v1"))
    models = cfg.setdefault("models", {})
    if os.getenv("NIM_CODER_PRIMARY"):
        models["coder_primary"] = os.environ["NIM_CODER_PRIMARY"]
    if os.getenv("NIM_CODER_FALLBACK"):
        models["coder_fallback"] = os.environ["NIM_CODER_FALLBACK"]
    if os.getenv("NIM_CRITIC"):
        models["critic"] = os.environ["NIM_CRITIC"]
    if os.getenv("NIM_SUMMARIZER"):
        models["summarizer"] = os.environ["NIM_SUMMARIZER"]
    if os.getenv("NIM_MAX_RPM"):
        cfg["max_rpm"] = int(os.environ["NIM_MAX_RPM"])
    return cfg


def resolve_path(rel: str | Path) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p
