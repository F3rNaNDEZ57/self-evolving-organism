"""Free-NIM multi-model router: role → pin + session budget tracking."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from organism.config import nim_config
from organism.nim_client import ChatResult, NimClient

# Canonical roles for Phase 3 pool
ROLES = ("plan", "code", "critique", "summarize", "coder", "critic", "summarizer")

# Map aliases → pin keys in nim.pinned.yaml models.*
ROLE_TO_PIN_KEY = {
    "plan": "summarizer",  # cheap plan/distill; free-tier
    "code": "coder_primary",
    "coder": "coder_primary",
    "critique": "critic",
    "critic": "critic",
    "summarize": "summarizer",
    "summarizer": "summarizer",
    "coder_fallback": "coder_fallback",
}


@dataclass
class BudgetState:
    max_rpm: int = 40
    max_tokens_session: int = 200_000
    max_calls_session: int = 200
    max_mutations: int = 30
    tokens_used: int = 0
    calls_used: int = 0
    mutations_used: int = 0
    by_role: dict[str, int] = field(default_factory=dict)
    by_model: dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens_session - self.tokens_used)

    def remaining_calls(self) -> int:
        return max(0, self.max_calls_session - self.calls_used)

    def can_call(self, estimated_tokens: int = 0) -> bool:
        if self.calls_used >= self.max_calls_session:
            return False
        if self.tokens_used + estimated_tokens > self.max_tokens_session:
            return False
        return True

    def can_mutate(self) -> bool:
        return self.mutations_used < self.max_mutations

    def record(self, result: ChatResult) -> None:
        tin = int(result.tokens_in or 0)
        tout = int(result.tokens_out or 0)
        total = tin + tout
        self.tokens_used += total
        self.calls_used += 1
        role = result.role or "other"
        self.by_role[role] = self.by_role.get(role, 0) + total
        self.by_model[result.model] = self.by_model.get(result.model, 0) + total

    def record_mutation(self) -> None:
        self.mutations_used += 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["remaining_tokens"] = self.remaining_tokens()
        d["remaining_calls"] = self.remaining_calls()
        return d


class FreeNimRouter:
    """
    Select free NIM models by task role and enforce session budgets.
    Does not introduce paid models; pins come from nim.pinned.yaml / env.
    """

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        *,
        budget: BudgetState | None = None,
        client: NimClient | None = None,
    ) -> None:
        self.cfg = cfg or nim_config()
        models = self.cfg.get("models") or {}
        self._models = dict(models)
        pool = self.cfg.get("pool") or {}
        # optional pool overrides: {code: model_id, ...}
        for k, v in pool.items():
            if isinstance(v, str) and v.strip():
                pin_key = ROLE_TO_PIN_KEY.get(k, k)
                if pin_key in self._models or k in ROLE_TO_PIN_KEY:
                    self._models[pin_key] = v
        bcfg = self.cfg.get("budget") or {}
        self.budget = budget or BudgetState(
            max_rpm=int(self.cfg.get("max_rpm", bcfg.get("max_rpm", 40))),
            max_tokens_session=int(bcfg.get("max_tokens_session", 200_000)),
            max_calls_session=int(bcfg.get("max_calls_session", 200)),
            max_mutations=int(bcfg.get("max_mutations", 30)),
        )
        self._client = client

    def model_for(self, role: str) -> str:
        role = (role or "code").lower().strip()
        pin_key = ROLE_TO_PIN_KEY.get(role, "coder_primary")
        model = self._models.get(pin_key) or self._models.get("coder_primary") or ""
        if not model:
            raise RuntimeError(f"No free NIM pin for role={role!r} key={pin_key!r}")
        return model

    def pins(self) -> dict[str, str]:
        return {
            "code": self.model_for("code"),
            "critique": self.model_for("critique"),
            "summarize": self.model_for("summarize"),
            "plan": self.model_for("plan"),
            "coder_fallback": self._models.get("coder_fallback", ""),
            "base_url": str(self.cfg.get("base_url", "")),
            "max_rpm": str(self.budget.max_rpm),
        }

    def client(self) -> NimClient:
        if self._client is None:
            self._client = NimClient(self.cfg, on_call=self.budget.record)
        elif self._client.on_call is None:
            self._client.on_call = self.budget.record
        return self._client

    def chat(
        self,
        role: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
        fallback_role: str | None = None,
    ) -> ChatResult:
        if not self.budget.can_call(estimated_tokens=max_tokens):
            raise RuntimeError(
                f"session budget exhausted: tokens={self.budget.tokens_used}/"
                f"{self.budget.max_tokens_session} calls={self.budget.calls_used}/"
                f"{self.budget.max_calls_session}"
            )
        use_model = model or self.model_for(role)
        client = self.client()
        # ensure RPM matches router budget
        client.max_rpm = self.budget.max_rpm
        try:
            return client.chat(
                messages,
                model=use_model,
                max_tokens=max_tokens,
                temperature=temperature,
                role=role,
            )
        except Exception:
            if fallback_role is None and role in ("code", "coder"):
                fallback_role = "coder_fallback"
            if fallback_role:
                fb = self.model_for(fallback_role) if fallback_role != "coder_fallback" else (
                    self._models.get("coder_fallback") or self.model_for("critique")
                )
                return client.chat(
                    messages,
                    model=fb,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    role=f"{role}_fallback",
                )
            raise

    def to_dict(self) -> dict[str, Any]:
        return {
            "pins": self.pins(),
            "budget": self.budget.to_dict(),
        }
