from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from app.engine import RiskEngine
from app.scoring import combine, extract_signals


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/replay.py events.jsonl [out.csv]")
    src = Path(sys.argv[1])
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("replay.csv")
    engine = RiskEngine()
    rows = []
    for line in src.read_text().splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        batch = payload.get("transactions", [payload])
        for item in batch:
            before = None
            tx_id = item.get("txId", "")
            frm = item.get("fromUserId")
            to = item.get("toUserId")
            if isinstance(frm, str) and isinstance(to, str):
                src_i = engine.graph.intern(frm)
                dest_i = engine.graph.intern(to)
                engine.reach.ensure_fresh()
                before = extract_signals(engine.graph, engine.reach, src_i, dest_i)
            scored = engine.score_batch([item])[0]
            rows.append(
                {
                    "txId": scored["txId"],
                    "riskScore": scored["riskScore"],
                    "n_new": None if before is None else before.n_new,
                    "n_red": None if before is None else before.n_red,
                    "cycle_len": None if before is None else before.cycle_len,
                    "ret_mult": None if before is None else before.ret_mult,
                    "scc_size": None if before is None else before.scc_size,
                }
            )
    with dest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["txId"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {dest} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
