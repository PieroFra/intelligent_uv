# pylint: disable=invalid-name
"""Intelligent UV Mapping — RIZOMUV LUA SCRIPT BUILDER"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

__all__ = [
    "build_lua_script", "build_lua_steps", "render_lua_steps",
    "serialize_lua_value", "to_lua_path", "print_example",
]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

LuaValue = Union[None, bool, int, float, str, Mapping[str, Any], Sequence[Any]]


def to_lua_path(path: Any) -> str:
    """Converts a filesystem path to the forward-slash form Lua expects."""
    return str(path).replace("\\", "/")


def _escape_lua_string(value: str) -> str:
    escaped = []
    for ch in value:
        if ch == "\\":
            escaped.append("\\\\")
        elif ch == '"':
            escaped.append('\\"')
        elif ch == "\n":
            escaped.append("\\n")
        elif ch == "\r":
            escaped.append("\\r")
        elif ch == "\t":
            escaped.append("\\t")
        elif ord(ch) < 0x20:
            escaped.append(f"\\{ord(ch):03o}")
        else:
            escaped.append(ch)
    return "".join(escaped)


def _format_lua_number(value: Union[int, float]) -> str:
    if isinstance(value, bool):
        raise TypeError("Booleans are not numbers in the Lua serializer.")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6f}"
    raise TypeError(f"Unsupported numeric type: {type(value)!r}")


def _serialize_lua_key(key: str) -> str:
    """
    Serialize a Lua table key.

    Valid Lua identifiers are emitted bare:      File={Path="..."}
    Anything else needs bracket syntax:          {["my key"]=1}
    Emitting a bare quoted key is a Lua syntax error.
    """
    key = str(key)
    if _IDENTIFIER_RE.match(key):
        return key
    return f'["{_escape_lua_string(key)}"]'


def serialize_lua_value(value: LuaValue) -> str:
    """Renders a Python value as the Lua literal RizomUV will parse."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_lua_number(value)
    if isinstance(value, str):
        return f'"{_escape_lua_string(value)}"'
    if isinstance(value, Mapping):
        if not value:
            return "{}"
        parts = []
        for key, item in value.items():
            parts.append(f"{_serialize_lua_key(key)}={serialize_lua_value(item)}")
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        return "{" + ", ".join(serialize_lua_value(i) for i in value) + "}"
    raise TypeError(f"Unsupported Lua value type: {type(value)!r}")


def _serialize_lua_call(command: str, params: Optional[Mapping[str, Any]]) -> str:
    command = str(command)
    if not command:
        raise ValueError("Lua step command must not be empty.")
    if not params:
        return f"{command}()"
    return f"{command}({serialize_lua_value(params)})"


def render_lua_steps(steps: Iterable[Mapping[str, Any]]) -> str:
    """Turns a list of (command, parameters) into Lua source."""
    lines = []
    for step in steps:
        command = step.get("command")
        if not command:
            raise ValueError(f"Lua step is missing 'command': {step!r}")
        params = step.get("params") or {}
        lines.append(_serialize_lua_call(command, params))
    return "\n".join(lines) + "\n"


def build_lua_steps(export_path, import_path, margin_uv, *,
                    texture_resolution=None, margin_px=None):
    """The command sequence for a load, pack and save round trip."""
    export_lua_path = to_lua_path(export_path)
    import_lua_path = to_lua_path(import_path)

    # RizomUV packs in pixel units by default (UsePixelUnit=true): the UV-unit
    # MarginSize/SpacingSize passed to ZomPack used to be ignored, so the pack
    # ran with whatever padding the last session had. The values that actually
    # drive the packer live in the document at
    # Lib.Mesh.RootGroup.Properties.Pack — write them explicitly.
    tex_res = max(64, int(texture_resolution or 2048))
    pad_px = max(1, int(round(float(margin_px if margin_px is not None
                                        else margin_uv * tex_res))))
    pack_root = "Lib.Mesh.RootGroup.Properties.Pack"

    steps = [
        {"command": "ZomLoad", "params": {
            "File": {"Path": export_lua_path, "ImportGroups": True, "XYZUVW": True}}},
    ]
    for path, value in (
        (f"{pack_root}.MapResolution", tex_res),
        (f"{pack_root}.UsePixelUnit", True),
        (f"{pack_root}.PaddingSizePx", pad_px),
        (f"{pack_root}.MarginSizePx", pad_px),
        (f"{pack_root}.Scaling.Mode", 0),
    ):
        steps.append({"command": "ZomSet", "params": {"Path": path, "Value": value}})

    steps.extend([
        {"command": "ZomPack", "params": {
            "RootGroup": "RootGroup", "WorkingSet": "Visible",
            "Translate": True, "Rotate": {"Mode": 4}}},
        {"command": "ZomSave", "params": {
            "File": {"Path": import_lua_path, "UVWProps": True}}},
        {"command": "ZomQuit", "params": {}},
    ])
    return steps


def build_lua_script(export_path, import_path, margin_uv, *,
                     texture_resolution=None, margin_px=None):
    """Complete Lua script for one RizomUV run."""
    return render_lua_steps(build_lua_steps(
        export_path=export_path, import_path=import_path, margin_uv=margin_uv,
        texture_resolution=texture_resolution, margin_px=margin_px))


def _example_paths():
    return {"export_path": "C:/Temp/iuv_example_export.fbx",
            "import_path": "C:/Temp/iuv_example_import.fbx"}


def print_example(margin_uv: float = 0.002345) -> None:
    """Prints a sample script, for checking the syntax by eye."""
    paths = _example_paths()
    script = build_lua_script(export_path=paths["export_path"],
        import_path=paths["import_path"], margin_uv=margin_uv,
        texture_resolution=1024, margin_px=2)
    print("[rizomuv_script] Generated script:")
    print(script, end="")


if __name__ == "__main__":
    print_example()
