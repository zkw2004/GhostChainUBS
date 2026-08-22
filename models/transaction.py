from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


class IdempotencyConflict(Exception):
    """Same txId submitted again with a different payload."""

    def __init__(self, tx_id: str):
        super().__init__(f"txId {tx_id!r} was already processed with a different payload")
        self.tx_id = tx_id


def parse_created_at(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("createdAt must be an ISO 8601 timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("createdAt must be an ISO 8601 timestamp") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Transaction:
    tx_id: str
    from_user_id: str
    to_user_id: str
    amount: float
    created_at: datetime
    ip_address: Optional[str] = None
    device_id: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: Any) -> "Transaction":
        """Build a transaction from JSON. Unknown fields are ignored."""
        if not isinstance(raw, dict):
            raise ValueError("each transaction must be an object")

        tx_id = raw.get("txId")
        from_user_id = raw.get("fromUserId")
        to_user_id = raw.get("toUserId")
        amount = raw.get("amount")
        created_at = raw.get("createdAt")

        if not isinstance(tx_id, str) or not tx_id:
            raise ValueError("txId is required")
        if not isinstance(from_user_id, str) or not from_user_id:
            raise ValueError("fromUserId is required")
        if not isinstance(to_user_id, str) or not to_user_id:
            raise ValueError("toUserId is required")
        if amount is None:
            raise ValueError("amount is required")
        try:
            amount_value = float(amount)
        except (TypeError, ValueError) as exc:
            raise ValueError("amount must be a number") from exc

        ip_address = raw.get("ipAddress")
        device_id = raw.get("deviceId")
        if ip_address is not None:
            ip_address = str(ip_address)
        if device_id is not None:
            device_id = str(device_id)

        return cls(
            tx_id=tx_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            amount=amount_value,
            created_at=parse_created_at(created_at),
            ip_address=ip_address,
            device_id=device_id,
        )

    def fingerprint(self) -> tuple:
        """Identity used to decide whether a replayed txId is the same payload."""
        return (
            self.from_user_id,
            self.to_user_id,
            self.amount,
            self.created_at,
            self.ip_address,
            self.device_id,
        )
