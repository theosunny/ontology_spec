#!/usr/bin/env python3
"""Execute (or dry-run) one action from model.actions.yaml.

Pipeline per action: governance gate -> precondition check -> binding -> audit log.

Dry run (default) renders the full execution plan without touching a database.
Real run:  set NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD and pip install neo4j.

Usage:
  python tools/run_action.py assign_actor_to_movie --param actor_id=nm1 --param movie_id=mv1
  python tools/run_action.py delete_movie --param movie_id=mv1 [--param genre=...] --execute
  (--example examples/other  to point at another example directory; default examples/movies)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTIONS_YAML = ROOT / "examples" / "movies" / "model.actions.yaml"
AUDIT = ROOT / "examples" / "movies" / "dist" / "audit.jsonl"


def parse_args(argv: list[str]) -> tuple[str, dict, bool, str | None]:
    if not argv:
        raise SystemExit(__doc__)
    action_id, rest = argv[0], argv[1:]
    params: dict[str, str] = {}
    execute = False
    example: str | None = None
    it = iter(rest)
    for tok in it:
        if tok == "--execute":
            execute = True
        elif tok == "--example":
            try:
                example = next(it)
            except StopIteration:
                raise SystemExit("--example needs a directory path")
        elif tok == "--param":
            try:
                kv = next(it)
            except StopIteration:
                raise SystemExit("--param needs key=value")
            if "=" not in kv:
                raise SystemExit(f"--param expects key=value, got '{kv}'")
            k, v = kv.split("=", 1)
            params[k] = v
    return action_id, params, execute, example


def check_params(action: dict, params: dict) -> list[str]:
    problems = []
    for pid, p in action["parameters"].items():
        if p.get("required") and pid not in params:
            problems.append(f"missing required parameter: {pid}")
        if pid in params and "enum" in p and params[pid] not in p["enum"]:
            problems.append(f"{pid}={params[pid]!r} not in enum {p['enum']}")
    extra = set(params) - set(action["parameters"])
    for pid in extra:
        problems.append(f"unknown parameter: {pid}")
    return problems


def audit(action_id: str, params: dict, status: str) -> None:
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": datetime.now(timezone.utc).isoformat(),
             "action": action_id, "params": params, "status": status}
    with open(AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> int:
    global ACTIONS_YAML, AUDIT
    if hasattr(sys.stdout, "reconfigure"):  # Windows GBK console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    action_id, params, execute, example = parse_args(sys.argv[1:])
    if example:
        ex = Path(example)
        if not ex.is_absolute():
            ex = (ROOT / ex).resolve()
        ACTIONS_YAML = ex / "model.actions.yaml"
        AUDIT = ex / "dist" / "audit.jsonl"
    doc = yaml.safe_load(ACTIONS_YAML.read_text(encoding="utf-8"))
    action = doc["actions"].get(action_id)
    if action is None:
        print(f"ERROR unknown action '{action_id}'. "
              f"Available: {', '.join(doc['actions'])}")
        return 1

    gov = action["governance"]
    print(f"▶ action      : {action_id} — {action['title']}")
    print(f"  risk        : {gov['risk']}"
          + ("  [APPROVAL REQUIRED — gate closed]" if gov.get("approval") else ""))
    print(f"  reversible  : {gov['reversible']}")

    problems = check_params(action, params)
    for p in problems:
        print(f"ERROR {p}")
    if problems:
        audit(action_id, params, "rejected:invalid-params")
        return 1
    print(f"  params      : OK  {params}")

    if gov.get("approval") and execute:
        print("ERROR governance: risk 'high' requires approval; refusing to execute. "
              "Clear the approval gate in your workflow first.")
        audit(action_id, params, "rejected:approval-gate")
        return 1

    print("\n1) precondition check:")
    print("   " + action["preconditions"]["check"].strip().replace("\n", "\n   "))

    binding = action["binding"]
    print("\n2) binding:")
    if binding["kind"] == "cypher":
        print("   " + binding["cypher"].strip().replace("\n", "\n   "))
    else:
        print(f"   {binding['kind']}: {binding}")

    if gov.get("reversible"):
        print("\n3) undo (kept for rollback):")
        print("   " + gov["undo"].strip().replace("\n", "\n   "))

    if not execute:
        print("\n— dry run complete; nothing executed. Add --execute (needs NEO4J_URI "
              "+ `pip install neo4j`) to run for real.")
        return 0

    if not os.environ.get("NEO4J_URI"):
        print("ERROR --execute needs NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD")
        return 1
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("ERROR `pip install neo4j` first")
        return 1

    driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
                                  auth=(os.environ.get("NEO4J_USER", "neo4j"),
                                        os.environ.get("NEO4J_PASSWORD", "")))
    with driver.session() as session:
        ok = session.run(action["preconditions"]["check"], **params).single().value()
        if not ok:
            print("ERROR precondition check returned false — refusing to execute")
            audit(action_id, params, "rejected:precondition")
            return 1
        session.run(binding["cypher"], **params).consume()
    driver.close()
    audit(action_id, params, "executed")
    print("\n✔ executed; audit written to dist/audit.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
