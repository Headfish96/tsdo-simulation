"""Recompute archived observations, without deploying or synthesizing samples."""

import hashlib
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarize(rows):
    if not rows:
        raise ValueError("Empty observations")
    summary = {"n": len(rows)}
    for key in ("total_time", "partial_exposure_time"):
        values = [row[key] for row in rows]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
            raise ValueError(f"Invalid duration: {key}")
        summary[key] = {
            "mean_s": statistics.mean(values),
            "median_s": statistics.median(values),
            "population_std_s": statistics.pstdev(values),
            "min_s": min(values),
            "max_s": max(values),
        }
    if any(row["partial_exposure_time"] > row["total_time"] for row in rows):
        raise ValueError("Partial duration exceeds total duration")
    return summary


def report():
    results = ROOT / "legacy" / "results"
    output = {}
    for name in ("baseline", "tsdo"):
        rows = json.loads((results / f"{name}_times.json").read_text())
        output[name] = summarize(rows)
    base = output["baseline"]["total_time"]["mean_s"]
    proposed = output["tsdo"]["total_time"]["mean_s"]
    output["archived_total_time_reduction_percent"] = (base - proposed) / base * 100
    output["provenance"] = "Reanalysis of existing local JSON; not a fresh cluster benchmark."
    output["warning"] = "Partial exposure definitions differ; do not interpret as a fair reduction comparison."
    output["sha256"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "legacy").rglob("*")) if path.is_file()
    }
    return output


if __name__ == "__main__":
    print(json.dumps(report(), indent=2, ensure_ascii=False))
