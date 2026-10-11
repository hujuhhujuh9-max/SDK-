#!/usr/bin/env python3
"""Recompute 2D evidence gates from hashed raw captures and the fixed limits."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.scale_evidence import SPEC, evaluate_bundle
from scripts.scale_functionality import evaluate_functionality


def summarize(spec, results, functionality=None):
    missing = []
    for workload in ("renpy", "canvas", "table", "rive"):
        for engine in spec["workloads"][workload]["engines"]:
            for repetition in range(1, spec["measurement"]["repetitions"] + 1):
                if not any(result.get("kind") == "frames" and result.get("workload") == workload
                           and result.get("tier") == "nominal" and result.get("engine") == engine
                           and result.get("repetition") == repetition for result in results):
                    missing.append(f"{workload}/{engine} nominal frame window {repetition}")
    for workload in ("canvas", "table"):
        if not any(result.get("kind") == "input" and result.get("workload") == workload
                   and result.get("tier") == "nominal" for result in results):
            missing.append(workload + " visible input measurements")
    for kind, description in (("memory", "ten-cycle whole-process memory trend"),
                              ("startup", "five cold launches to visible enabled control")):
        if not any(result.get("kind") == kind for result in results):
            missing.append(description)
    identities = {(result.get("apk_sha256"), result.get("source_sha"),
                   result.get("project_input_sha256"), result.get("device_sha256"))
                  for result in results if result.get("apk_sha256")}
    if len(identities) > 1:
        missing.append("performance evidence refers to different APKs, source/project inputs or phones")
    if functionality is None or functionality.get("status") != "pass":
        missing.append("combined save/reopen/background/return functionality observations")
    elif any((identity[1], identity[2]) != (functionality["source_sha"], functionality["project_input_sha256"])
             for identity in identities):
        missing.append("functionality and physical runs use different SDK/project inputs")
    status = "fail" if any(item["status"] == "fail" for item in results) else (
        "unverified" if missing or not results or any(item["status"] != "pass" for item in results) else "pass")
    return {"profile": spec["profile"], "status": status, "measurements": results,
            "functionality": functionality, "missing": missing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="*", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace-processor", type=Path,
                        help="Perfetto trace_processor_shell; required for a verified frame gate")
    parser.add_argument("--functionality", type=Path,
                        help="Combined driver capabilities-device.json with hashed raw observations")
    args = parser.parse_args()
    spec = json.loads(SPEC.read_text())
    results = []
    for folder in args.folders:
        try:
            results.append(evaluate_bundle(folder, spec, trace_processor=args.trace_processor))
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, ElementTree.ParseError) as error:
            results.append({"folder": str(folder), "status": "unverified", "reasons": [str(error)]})
    functionality = None
    if args.functionality:
        try:
            functionality = evaluate_functionality(args.functionality)
        except (ValueError, RuntimeError, OSError, KeyError, TypeError, ImportError, ElementTree.ParseError) as error:
            functionality = {"status": "unverified", "receipt": str(args.functionality), "reasons": [str(error)]}
    result = summarize(spec, results, functionality)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
