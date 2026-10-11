"""The numbers credits are worked out from: the rate card, wallets and caps of the signed policy,
with built-in defaults until a policy has them (see docs/credits.md)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from packaging.version import InvalidVersion, Version

_logger = logging.getLogger("vethuq.credits")


def milli(credits: float) -> int:
    """Credits as whole milli-credits, so amounts never drift."""
    return round(float(credits) * 1000)


def number(value: Any, default: float, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < minimum:
        return default
    return float(value)


@dataclass(frozen=True)
class _Promotion:
    id: str
    name: str
    start: str  # first UTC day, inclusive (YYYY-MM-DD)
    end: str  # last UTC day, inclusive
    # Per wallet: {"percent": of the base daily amount} or {"absolute": credits}.
    uplift: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    message: str = ""

    def active(self, day: date) -> bool:
        return self.start <= day.isoformat() <= self.end

    def uplift_milli(self, wallet: str, base_milli: int, cap_percent: float) -> int:
        entry = self.uplift.get(wallet, {})
        amount = milli(entry.get("absolute") or 0) + round(
            base_milli * (entry.get("percent") or 0) / 100
        )
        return min(amount, round(base_milli * cap_percent / 100))


@dataclass(frozen=True)
class _Terms:
    rate_card_version: int = 1
    tolerance_percent: float = 5.0
    step: float = 0.25
    minimum: float = 0.25
    per_page_max: float = 16.0
    quick: float = 1.0
    language_pass: float = 1.0
    rotated_factor: float = 0.8
    cpu: float = 1.0
    fast: float = 1.0
    local_daily: float = 500.0
    local_starter: float = 2000.0
    github_daily_private: float = 20.0
    github_daily_public: float = 200.0
    github_starter: float = 0.0
    grace_percent: float = 2.0
    grace_mode: str = "free"
    bonus_percent: float = 10.0
    bonus_cap_percent: float = 15.0
    promotion_cap_percent: float = 100.0
    one_off_max: float | None = None
    one_off_expiry_days: int = 365
    device_daily_ceiling: float | None = None
    metrics_enabled: bool = True
    metrics_endpoint: str = ""
    metrics_max_batch_bytes: int = 65536
    promotions: tuple[_Promotion, ...] = field(default_factory=tuple)

    # ----- reading ----------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> _Terms:
        known = _Terms.__dataclass_fields__
        values = {k: v for k, v in data.items() if k in known and k != "promotions"}
        promotions = tuple(_Promotion(**p) for p in data.get("promotions", ()))
        return _Terms(**values, promotions=promotions)

    @staticmethod
    def _applies(
        section: Mapping[str, Any], default: Mapping[str, Any] | None, version: str
    ) -> bool:
        scope = section.get("applies_to", default)
        if not isinstance(scope, Mapping):
            return True
        client = scope.get("client")
        if not isinstance(client, Mapping):
            return True
        try:
            current = Version(version)
            low, high = client.get("min"), client.get("max")
            return (low is None or current >= Version(low)) and (
                high is None or current <= Version(high)
            )
        except (InvalidVersion, TypeError):
            return True

    @staticmethod
    def from_policy(raw: Mapping[str, Any], client_version: str = "0.0.0") -> _Terms:
        """The terms in a verified policy payload; whatever it leaves out stays at the default.
        A section that doesn't apply to this client version is ignored."""
        base = _Terms()
        values: dict[str, Any] = {}
        default_scope = raw.get("applies_to")

        def section(name: str) -> Mapping[str, Any]:
            value = raw.get(name)
            if isinstance(value, Mapping) and _Terms._applies(value, default_scope, client_version):
                return value
            return {}

        card = section("rate_card")
        size = card.get("page_size") if isinstance(card.get("page_size"), Mapping) else {}
        phases = card.get("phases") if isinstance(card.get("phases"), Mapping) else {}
        device = card.get("device_multiplier")
        device = device if isinstance(device, Mapping) else {}
        model = (
            card.get("model_multiplier")
            if isinstance(card.get("model_multiplier"), Mapping)
            else {}
        )
        version = card.get("version")
        if isinstance(version, int) and not isinstance(version, bool) and version >= 1:
            values["rate_card_version"] = version
        values["tolerance_percent"] = number(size.get("tolerance_percent"), base.tolerance_percent)
        values["step"] = number(size.get("step"), base.step, 0.001)
        values["minimum"] = number(size.get("minimum"), base.minimum)
        values["per_page_max"] = number(size.get("per_page_max"), base.per_page_max, 0.001)
        values["quick"] = number(phases.get("quick"), base.quick)
        values["language_pass"] = number(card.get("language_pass"), base.language_pass)
        values["rotated_factor"] = number(card.get("rotated_factor"), base.rotated_factor)
        values["cpu"] = number(device.get("cpu"), base.cpu)
        values["fast"] = number(model.get("fast"), base.fast)

        wallets = section("wallets")
        local = wallets.get("local") if isinstance(wallets.get("local"), Mapping) else {}
        values["local_daily"] = number(local.get("daily"), base.local_daily)
        values["local_starter"] = number(local.get("starter"), base.local_starter)
        github = wallets.get("github") if isinstance(wallets.get("github"), Mapping) else {}
        values["github_daily_private"] = number(
            github.get("daily_private"), base.github_daily_private
        )
        values["github_daily_public"] = number(github.get("daily_public"), base.github_daily_public)
        values["github_starter"] = number(github.get("starter"), base.github_starter)

        caps = section("caps")
        values["promotion_cap_percent"] = number(
            caps.get("promotion_uplift_percent"), base.promotion_cap_percent, 0.001
        )
        values["bonus_cap_percent"] = number(
            caps.get("metrics_bonus_percent"), base.bonus_cap_percent
        )
        if "one_off_max" in caps:
            values["one_off_max"] = number(caps.get("one_off_max"), 0.0) or None
        expiry = caps.get("one_off_expiry_days")
        if isinstance(expiry, int) and not isinstance(expiry, bool) and expiry >= 1:
            values["one_off_expiry_days"] = expiry
        if "device_daily_ceiling" in caps:
            values["device_daily_ceiling"] = number(caps.get("device_daily_ceiling"), 0.0) or None

        for key in ("grace_percent", "grace_mode"):
            if key in raw and _Terms._applies({}, default_scope, client_version):
                if key == "grace_percent":
                    values[key] = min(number(raw[key], base.grace_percent), 100.0)
                elif raw[key] in ("free", "borrow"):
                    values[key] = raw[key]

        metrics = section("metrics")
        if isinstance(metrics.get("enabled"), bool):
            values["metrics_enabled"] = metrics["enabled"]
        if isinstance(metrics.get("endpoint"), str):
            values["metrics_endpoint"] = metrics["endpoint"]
        batch = metrics.get("max_batch_bytes")
        if isinstance(batch, int) and not isinstance(batch, bool) and batch > 0:
            values["metrics_max_batch_bytes"] = batch
        values["bonus_percent"] = number(metrics.get("bonus_percent"), base.bonus_percent)

        values["promotions"] = _Terms._promotions(raw.get("promotions"), client_version)
        return _Terms(**values)

    @staticmethod
    def _promotions(value: Any, client_version: str) -> tuple[_Promotion, ...]:
        found: list[_Promotion] = []
        for item in value if isinstance(value, list) else []:
            try:
                uplift = {
                    wallet: dict(entry)
                    for wallet, entry in item["uplift"].items()
                    if wallet in ("local", "github") and isinstance(entry, Mapping)
                }
                if not uplift:
                    continue
                if not _Terms._applies(item, None, client_version):
                    continue
                minimum = item.get("min_client")
                if minimum and Version(client_version) < Version(minimum):
                    continue
                found.append(
                    _Promotion(
                        id=str(item["id"]),
                        name=str(item["name"]),
                        start=str(item["start_date"]),
                        end=str(item["end_date"]),
                        uplift=uplift,
                        message=str(item.get("message", "")),
                    )
                )
            except (KeyError, TypeError, AttributeError, InvalidVersion):
                _logger.warning("Ignoring a promotion that couldn't be read")
        return tuple(found)

    # ----- derived ----------------------------------------------------------------------------

    def daily_for(self, wallet: str, private: bool = True) -> float:
        """A wallet's daily allowance. The GitHub one depends on the runner repo's visibility."""
        if wallet == "github":
            return self.github_daily_private if private else self.github_daily_public
        return self.local_daily if wallet == "local" else 0.0

    def starter_for(self, wallet: str) -> float:
        return {"github": self.github_starter, "local": self.local_starter}.get(wallet, 0.0)

    def best_promotion(
        self, day: date, base_milli: int, wallet: str = "local"
    ) -> tuple[_Promotion, int] | None:
        """The active promotion with the biggest uplift for `wallet` (they don't stack)."""
        best: tuple[_Promotion, int] | None = None
        for promotion in self.promotions:
            if promotion.active(day):
                amount = promotion.uplift_milli(wallet, base_milli, self.promotion_cap_percent)
                if amount > 0 and (best is None or amount > best[1]):
                    best = (promotion, amount)
        return best
