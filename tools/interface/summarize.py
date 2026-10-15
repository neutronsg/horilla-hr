"""Summarize recorded browser samples without hiding errors or using best runs."""

import json
from pathlib import Path
from statistics import median

root = Path(__file__).resolve().parents[2] / "docs/interface"
data = {p: json.loads((root / f"{p}.json").read_text()) for p in ["before", "after"]}
fields = [
    "ttfb",
    "fcp",
    "dcl",
    "load",
    "resources",
    "requestCount",
    "decodedBytes",
    "transferBytes",
    "longTasks",
    "lastSwap",
]
summary = {}
for phase, records in data.items():
    summary[phase] = {}
    for name in dict.fromkeys(r["name"] for r in records):
        group = [r for r in records if r["name"] == name]
        summary[phase][name] = {
            k: round(median(r[k] for r in group), 2) for k in fields
        }
        summary[phase][name]["errors"] = sorted(
            set(e for r in group for e in r["errors"])
        )
        summary[phase][name]["backend"] = {}
        for pattern in [
            "/employees-list/",
            "/request-filter/",
            "/list-reimbursement/",
            "/payslip-list/",
        ]:
            timings = [
                t for r in group for t in r.get("backend", []) if pattern in t["url"]
            ]
            if timings:
                summary[phase][name]["backend"][pattern] = {
                    k: round(
                        median(
                            next(
                                (
                                    (
                                        float(t["description"])
                                        if k == "queries"
                                        else t["duration"]
                                    )
                                    for t in entry["timings"]
                                    if t["name"] == k
                                ),
                                0,
                            )
                            for entry in timings
                        ),
                        2,
                    )
                    for k in ["app", "sql", "queries"]
                }
(root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print("| Page | DOM ready, ms | Requests | Decoded MB |")
print("|---|---:|---:|---:|")
for name, before in summary["before"].items():
    after = summary["after"][name]
    print(
        f'| {name} | {before["dcl"]:.0f} → {after["dcl"]:.0f} | {before["requestCount"]:.0f} → {after["requestCount"]:.0f} | {before["decodedBytes"]/1e6:.2f} → {after["decodedBytes"]/1e6:.2f} |'
    )
