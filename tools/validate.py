#!/usr/bin/env python3
"""Cross-document validator for the ontology + actions pipeline.

Validates three layers:
  1. model.ontology.yaml  against the official ontology-graph-spec JSON Schema (1.1.0)
  2. model.actions.yaml   against schemas/actions.schema.json
  3. cross-document rules binding the two together (references, types, governance)

Exit code 0 = valid, 1 = errors found.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "examples" / "movies"
ONTOLOGY_YAML = EXAMPLE / "model.ontology.yaml"
ACTIONS_YAML = EXAMPLE / "model.actions.yaml"
ONTOLOGY_SCHEMA = ROOT / "schemas" / "ontology-graph-spec.schema.json"
ACTIONS_SCHEMA = ROOT / "schemas" / "actions.schema.json"

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"{path.name}: document must be a YAML mapping")
    return data


def json_validate(doc: dict, schema_path: Path, label: str) -> None:
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8")) \
        if schema_path.suffix in (".yaml", ".yml") \
        else __import__("json").loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        err(f"[{label}] {loc}: {e.message}")


def ontology_property(onto: dict, binds: dict) -> tuple[dict | None, str]:
    """Resolve a binds clause to the ontology property definition it points at."""
    if "node" in binds:
        node = onto.get("nodes", {}).get(binds["node"])
        if node is None:
            return None, f"node '{binds['node']}' not defined in ontology"
        prop = node.get("properties", {}).get(binds["property"])
        if prop is None:
            return None, f"node '{binds['node']}' has no property '{binds['property']}'"
        return prop, ""
    rel = onto.get("relationships", {}).get(binds["relationship"])
    if rel is None:
        return None, f"relationship '{binds['relationship']}' not defined in ontology"
    prop = rel.get("properties", {}).get(binds["property"])
    if prop is None:
        return None, f"relationship '{binds['relationship']}' has no property '{binds['property']}'"
    return prop, ""


def cross_validate(onto: dict, actions_doc: dict) -> None:
    # --- header coupling -----------------------------------------------------
    declared = actions_doc.get("ontology", {})
    if declared.get("id") != onto.get("id"):
        err(f"actions.ontology.id: '{declared.get('id')}' != ontology.id '{onto.get('id')}'")
    if declared.get("version") != onto.get("version"):
        err(f"actions.ontology.version: '{declared.get('version')}' != ontology.version "
            f"'{onto.get('version')}'")

    nodes = onto.get("nodes", {})
    rels = onto.get("relationships", {})

    for action_id, action in actions_doc.get("actions", {}).items():
        base = f"actions.{action_id}"

        # --- parameter bindings ---------------------------------------------
        for param_id, param in action.get("parameters", {}).items():
            p = f"{base}.parameters.{param_id}"
            binds = param.get("binds")
            if not binds:
                warn(f"{p}: no binds — parameter floats free of the ontology")
                continue
            prop, problem = ontology_property(onto, binds)
            if prop is None:
                err(f"{p}.binds: {problem}")
                continue
            if param.get("type") != prop.get("type"):
                err(f"{p}.type: '{param.get('type')}' != ontology type '{prop.get('type')}' "
                    f"at {binds}")
            one_of = prop.get("one_of")
            enum = param.get("enum")
            if one_of is not None and enum != one_of:
                err(f"{p}.enum: {enum} != ontology one_of {one_of} at {binds}")
            if enum is not None and one_of is None:
                warn(f"{p}.enum: enum set but ontology property has no one_of at {binds}")

        # --- targets ----------------------------------------------------------
        for i, target in enumerate(action.get("targets", [])):
            t = f"{base}.targets[{i}]"
            if "node" in target and target["node"] not in nodes:
                err(f"{t}.node: '{target['node']}' not defined in ontology")
            if "relationship" in target and target["relationship"] not in rels:
                err(f"{t}.relationship: '{target['relationship']}' not defined in ontology")

        # --- governance ---------------------------------------------------------
        gov = action.get("governance", {})
        if gov.get("risk") == "high" and not gov.get("approval"):
            err(f"{base}.governance: risk 'high' requires approval: true")

        # --- quality warnings (semantic payload for the LLM) --------------------
        if len(action.get("description", "")) < 16:
            warn(f"{base}.description: too short to reason from (<16 chars)")
        binding = action.get("binding", {})
        if binding.get("kind") == "cypher":
            texts = binding.get("cypher", "") + action.get("preconditions", {}).get("check", "")
            for param_id in action.get("parameters", {}):
                if f"${param_id}" not in texts:
                    warn(f"{base}.parameters.{param_id}: never referenced "
                         f"as ${param_id} in cypher/check")


def main() -> int:
    onto = load_yaml(ONTOLOGY_YAML)
    actions_doc = load_yaml(ACTIONS_YAML)

    json_validate(onto, ONTOLOGY_SCHEMA, "ontology")
    json_validate(actions_doc, ACTIONS_SCHEMA, "actions")
    cross_validate(onto, actions_doc)

    print(f"ontology : {ONTOLOGY_YAML.name}  (id={onto.get('id')}, version={onto.get('version')})")
    print(f"actions  : {ACTIONS_YAML.name}   (id={actions_doc.get('id')}, "
          f"version={actions_doc.get('version')}, {len(actions_doc.get('actions', {}))} actions)")
    print()

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    total = len(errors)
    print(f"\n{'INVALID' if total else 'VALID'}  "
          f"({total} error(s), {len(warnings)} warning(s))")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
