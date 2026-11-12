#!/usr/bin/env python3
"""Export the action set as an MCP tool manifest (dist/tools.mcp.json).

Each action becomes one tool: name / description / inputSchema, with the
description enriched with preconditions, effects and governance so an LLM
agent can reason about when to call it. The inputSchema is directly usable
as an MCP tool inputSchema (JSON Schema).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "examples" / "movies"
ACTIONS_YAML = EXAMPLE / "model.actions.yaml"
OUT = EXAMPLE / "dist" / "tools.mcp.json"

TYPE_MAP = {
    "STRING": {"type": "string"},
    "INTEGER": {"type": "integer"},
    "FLOAT": {"type": "number"},
    "BOOLEAN": {"type": "boolean"},
    "DATE": {"type": "string", "format": "date"},
    "UUID": {"type": "string", "format": "uuid"},
}


def input_schema(action: dict) -> dict:
    props = {}
    required = []
    for pid, p in action["parameters"].items():
        spec = dict(TYPE_MAP[p["type"]])
        if "description" in p:
            spec["description"] = p["description"]
        if "enum" in p:
            spec["enum"] = p["enum"]
        props[pid] = spec
        if p.get("required"):
            required.append(pid)
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


def tool_description(action: dict) -> str:
    gov = action["governance"]
    parts = [action["description"].strip()]
    parts.append(f"前置条件: {action['preconditions']['natural']}")
    parts.append(f"效果: {action['effects']['natural']}")
    note = f"风险: {gov['risk']}"
    if gov.get("approval"):
        note += "（需审批后执行）"
    if not gov.get("reversible"):
        note += "，不可逆"
    parts.append(note)
    return "\n".join(parts)


def main() -> int:
    doc = yaml.safe_load(ACTIONS_YAML.read_text(encoding="utf-8"))
    tools = []
    for aid, action in doc["actions"].items():
        tools.append({
            "name": aid,
            "title": action["title"],
            "description": tool_description(action),
            "inputSchema": input_schema(action),
        })

    manifest = {
        "server": {"name": doc["id"], "version": doc["version"]},
        "tools": tools,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"OK  {OUT.relative_to(ROOT)}")
    for t in tools:
        req = t["inputSchema"]["required"]
        print(f"    tool {t['name']}  params: {', '.join(t['inputSchema']['properties'])}"
              f"  required: {req if req else ['-']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
