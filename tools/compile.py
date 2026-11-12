#!/usr/bin/env python3
"""Compile source documents into the single-file distribution artifact.

Reads  model.ontology.yaml + model.actions.yaml
Writes dist/model.combined.yaml — the ontology with the action set embedded
under extensions.custom["acme.actions.v1"] (the spec's sanctioned escape hatch,
so the combined file still passes the official ontology-graph-spec JSON Schema
and round-trips through the Neo4j libraries untouched).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = "acme.actions.v1"  # rename to your org, e.g. "yourco.actions.v1"

EXAMPLE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "examples" / "movies"
ONTOLOGY_YAML = EXAMPLE / "model.ontology.yaml"
ACTIONS_YAML = EXAMPLE / "model.actions.yaml"
ONTOLOGY_SCHEMA = ROOT / "schemas" / "ontology-graph-spec.schema.json"
OUT = EXAMPLE / "dist" / "model.combined.yaml"


def main() -> int:
    onto = yaml.safe_load(ONTOLOGY_YAML.read_text(encoding="utf-8"))
    actions_doc = yaml.safe_load(ACTIONS_YAML.read_text(encoding="utf-8"))

    combined = copy.deepcopy(onto)
    combined.setdefault("extensions", {}).setdefault("custom", {})[NAMESPACE] = {
        "source": {"document": ACTIONS_YAML.name,
                   "version": actions_doc["version"],
                   "schema": actions_doc["schema"]},
        "actions": actions_doc["actions"],
    }

    # prove the artifact still satisfies the official schema
    schema = json.loads(ONTOLOGY_SCHEMA.read_text(encoding="utf-8"))
    problems = sorted(Draft202012Validator(schema).iter_errors(combined),
                      key=lambda e: list(e.absolute_path))
    for e in problems:
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        print(f"ERROR combined/{loc}: {e.message}", file=sys.stderr)
    if problems:
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        yaml.safe_dump(combined, f, sort_keys=False, allow_unicode=True, width=100)

    print(f"OK  {OUT.relative_to(ROOT)}")
    print(f"    embedded {len(actions_doc['actions'])} action(s) under "
          f"extensions.custom['{NAMESPACE}']")
    print("    combined file re-validated against official schema: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
