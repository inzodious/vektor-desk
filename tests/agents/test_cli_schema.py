import json
from pathlib import Path

import pytest

from desk.agents import briefs
from desk.agents.adapter import ClaudeCli, cli_schema
from desk.agents.desks import DESKS, get

SCHEMAS = sorted(Path("desk/agents/schemas").glob("*.json"))
DRAFT7 = {
    "type",
    "enum",
    "const",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "anyOf",
    "oneOf",
    "allOf",
    "not",
    "if",
    "then",
    "else",
    "title",
    "description",
    "default",
    "examples",
    "format",
    "minProperties",
    "maxProperties",
    "patternProperties",
    "propertyNames",
    "contains",
    "dependencies",
    "definitions",
    "$ref",
    "$comment",
}
MAPS = ("properties", "patternProperties", "definitions")


def desk_schemas():
    out = {name: briefs.schema_for(name) for name in DESKS if name not in ("skeptic", "strategy")}
    return out | {"skeptic": briefs.schema_file("skeptic"), "strategy": briefs.schema_file("strategy")}


def keywords(node, path="#"):
    if isinstance(node, list):
        for i, v in enumerate(node):
            yield from keywords(v, f"{path}/{i}")
        return
    if not isinstance(node, dict):
        return
    for k, v in node.items():
        yield k, path
        if k in MAPS and isinstance(v, dict):
            for name, sub in v.items():
                yield from keywords(sub, f"{path}/{k}/{name}")
        elif k in ("items", "additionalProperties", "not", "if", "then", "else", "contains", "propertyNames", "anyOf", "oneOf", "allOf"):
            yield from keywords(v, f"{path}/{k}")


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda p: p.name)
def test_schema_files_declare_no_meta_schema(path):
    assert "$schema" not in path.read_text() and "$id" not in path.read_text()


@pytest.mark.parametrize(("name", "schema"), sorted(desk_schemas().items()))
def test_cli_gets_draft7_keywords_only(name, schema, tmp_path):
    cmd = ClaudeCli().command(get(name), tmp_path / "system.md", schema)
    sent = json.loads(cmd[cmd.index("--json-schema") + 1])
    unknown = [(k, p) for k, p in keywords(sent) if k not in DRAFT7]
    assert unknown == [], f"{name}: the CLI's Ajv (draft-07, strict) rejects {unknown}"


def test_cli_schema_strips_meta_keys_but_not_property_names():
    raw = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "x", "type": "object", "properties": {"$schema": {"type": "string"}}}
    assert cli_schema(raw) == {"type": "object", "properties": {"$schema": {"type": "string"}}}
