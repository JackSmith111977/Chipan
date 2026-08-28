#!/usr/bin/env python3
"""API e2e: create research job, consume SSE until ready."""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8080"


def main() -> int:
    req = urllib.request.Request(
        f"{BASE}/api/research",
        data=json.dumps({"symbol": "hk01810", "strategy": "blend"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    created = json.load(urllib.request.urlopen(req, timeout=8))
    assert created.get("ok"), created
    job_id = created["id"]
    states = [created.get("state")]
    with urllib.request.urlopen(f"{BASE}/api/research/stream?id={job_id}", timeout=30) as res:
        assert "text/event-stream" in (res.headers.get("Content-Type") or "")
        buf = b""
        while True:
            chunk = res.read(256)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                text = frame.decode("utf-8", "replace")
                if not text.startswith("data:"):
                    continue
                job = json.loads(text[5:].strip())
                states.append(job.get("state"))
                if job.get("state") in {"ready", "error"}:
                    assert job.get("state") == "ready", job
                    assert job.get("result") or job.get("pack"), job
                    print(json.dumps({"ok": True, "id": job_id, "states": states}, ensure_ascii=False))
                    return 0
    print(json.dumps({"ok": False, "states": states}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
