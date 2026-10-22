# -*- coding: utf-8 -*-
"""Mappa dei simboli di Intelligent UV Mapping, solo AST (nessun import dell'addon).

Serve all'architetto per sapere file, classi, metodi e funzioni con i numeri di riga
senza caricare 11.700 righe nella propria memoria.

Uso (dentro Blender, cosi' non serve un Python di sistema):
    blender --factory-startup --background --python index_addon.py -- --out <file> [--filter NOME]
"""

import argparse
import ast
import os
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".opencode", "__pycache__", "dist", "build", ".venv", "venv"}


def _first_doc_line(node):
    doc = ast.get_docstring(node) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line[:90]
    return ""


def _sig(node):
    """Firma compatta: argomenti posizionali + defaults, senza il corpo."""
    args = node.args
    names = [a.arg for a in getattr(args, "posonlyargs", []) + args.args]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        names.append("*")
    names += [a.arg for a in args.kwonlyargs]
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return "(" + ", ".join(names) + ")"


def _module_map(path, root):
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="latin-1")
    tree = ast.parse(source, filename=str(path))
    rel = path.relative_to(root).as_posix()
    out = ["== {0} ({1} righe)".format(rel, source.count("\n") + 1)]
    doc = _first_doc_line(tree)
    if doc:
        out.append("   # " + doc)

    count = 0
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases if not isinstance(b, ast.Load))
            head = "  class {0}{1}".format(node.name, "(" + bases + ")" if bases else "")
            out.append("{0} :{1}".format(head, node.lineno))
            count += 1
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append("    def {0}{1} :{2}".format(item.name, _sig(item), item.lineno))
                    count += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append("  def {0}{1} :{2}".format(node.name, _sig(node), node.lineno))
            count += 1
        elif isinstance(node, ast.Assign):
            # Costanti di modulo utili (CLASSES, elenchi di classi, versioni).
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    out.append("  {0} = ... :{1}".format(target.id, node.lineno))
                    count += 1
    return out, count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--filter", default="")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    here = Path(__file__).resolve()
    root = here.parents[2]
    needle = args.filter.lower()

    blocks = []
    files = 0
    total = 0
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        try:
            lines, count = _module_map(path, root)
        except SyntaxError as exc:
            lines = ["== {0}  ERRORE DI SINTASSI riga {1}: {2}".format(
                path.relative_to(root).as_posix(), exc.lineno, exc.msg)]
            count = 0
        if needle and not any(needle in line.lower() for line in lines):
            continue
        blocks.append("\n".join(lines))
        files += 1
        total += count

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print("INDEX_OUT {0} file={1} simboli={2}".format(out_path, files, total))


if __name__ == "__main__":
    main()
