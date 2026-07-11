"""OpenAI-compatible NVIDIA NIM client (free endpoints)."""

from __future__ import annotations

import time
from typing import Any

from openai import OpenAI

from organism.config import nim_config


class NimClient:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or nim_config()
        key = self.cfg.get("api_key") or ""
        if not key:
            raise RuntimeError("NVIDIA_API_KEY missing — set in .env")
        self.client = OpenAI(base_url=self.cfg["base_url"], api_key=key)
        self.max_rpm = int(self.cfg.get("max_rpm", 40))
        self._last_call = 0.0

    def _throttle(self) -> None:
        # crude ~40 RPM spacing
        min_interval = 60.0 / max(1, self.max_rpm)
        elapsed = time.time() - self._last_call
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call = time.time()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        self._throttle()
        model = model or self.cfg["models"]["coder_primary"]
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as e:
                last_err = e
                time.sleep(2**attempt)
        raise RuntimeError(f"NIM chat failed: {last_err}")

    def pins(self) -> dict[str, str]:
        m = self.cfg.get("models", {})
        return {
            "coder_primary": m.get("coder_primary", ""),
            "coder_fallback": m.get("coder_fallback", ""),
            "critic": m.get("critic", ""),
            "summarizer": m.get("summarizer", ""),
            "base_url": self.cfg.get("base_url", ""),
        }
