"""Static validation of whitelist genome modules (kernel)."""

from __future__ import annotations

import ast
from pathlib import Path

from organism.genome_loader import WHITELIST

# Sibling modules + approved stdlib/numpy. Bare "organism" is NOT allowed —
# only explicit submodules in ALLOWED_ORGANISM_MODULES (full dotted path).
ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "heuristics",
        "memory_hooks",
        "policy",
        "numpy",
        "random",
        "math",
        "typing",
        "collections",
        "dataclasses",
        "enum",
        "abc",
        "functools",
        "itertools",
        "operator",
        "copy",
        "numbers",
        "__future__",
    }
)

# Genome may only touch these organism.* modules (full path match).
ALLOWED_ORGANISM_MODULES = frozenset(
    {
        "organism.schemas",
        "organism.weights",
        "organism.organism_api",
    }
)

FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "pathlib",
        "shutil",
        "importlib",
        "ctypes",
        "pickle",
        "marshal",
        "multiprocessing",
        "threading",
        "asyncio",
        "http",
        "urllib",
        "requests",
        "ftplib",
        "ssl",
        "pty",
        "signal",
        "resource",
        "tempfile",
        "glob",
        "io",  # file-ish; keep closed for safety
        "builtins",
        "code",
        "codeop",
        "compileall",
        "runpy",
        "pkgutil",
        "zipimport",
        "sqlite3",
        "webbrowser",
    }
)

FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__", "open", "input", "breakpoint"})


class GenomeValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _root_module(name: str | None) -> str | None:
    if not name:
        return None
    return name.split(".", 1)[0]


def _import_allowed(module_path: str | None) -> bool:
    """Return True if the full dotted import path is permitted for genomes."""
    if not module_path:
        return False
    name = module_path.lstrip(".")
    root = _root_module(name)
    if root is None:
        return False
    if root in FORBIDDEN_IMPORT_ROOTS:
        return False
    if root == "organism":
        # Exact allowlist on full path — bare `organism` and kernel modules denied.
        if name in ALLOWED_ORGANISM_MODULES:
            return True
        # Allow attribute-level from allowed modules only if someone writes
        # organism.schemas.X as a module path (unusual); deny subpackages of kernel.
        for allowed in ALLOWED_ORGANISM_MODULES:
            if name == allowed:
                return True
        return False
    return root in ALLOWED_IMPORT_ROOTS


def validate_source(filename: str, source: str) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return [f"{filename}: syntax error: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # e.g. import organism.nim_client  → full path on alias.name
                if not _import_allowed(alias.name):
                    errors.append(f"{filename}: forbidden import '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # relative imports of siblings only (heuristics/policy/memory_hooks)
                continue
            mod = node.module or ""
            if not _import_allowed(mod):
                errors.append(f"{filename}: forbidden import from '{mod}'")
        elif isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in FORBIDDEN_CALLS:
                errors.append(f"{filename}: forbidden call '{name}'")

    if filename == "policy.py":
        has_policy = any(
            isinstance(n, ast.ClassDef) and n.name == "Policy" for n in tree.body
        )
        if not has_policy:
            errors.append("policy.py: missing class Policy")
        else:
            for n in tree.body:
                if isinstance(n, ast.ClassDef) and n.name == "Policy":
                    methods = {
                        m.name
                        for m in n.body
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                    }
                    for req in ("reset", "act", "on_step_result"):
                        if req not in methods:
                            errors.append(f"policy.py: Policy missing method {req}")
    return errors


def validate_genome_dir(genome_dir: Path) -> list[str]:
    genome_dir = Path(genome_dir)
    errors: list[str] = []
    for name in WHITELIST:
        path = genome_dir / name
        if not path.exists():
            errors.append(f"missing file {name}")
            continue
        source = path.read_text(encoding="utf-8")
        errors.extend(validate_source(name, source))
    total_lines = 0
    for name in WHITELIST:
        p = genome_dir / name
        if p.exists():
            total_lines += len(p.read_text(encoding="utf-8").splitlines())
    if total_lines > 500:
        errors.append(f"genome too large: {total_lines} lines (max 500)")
    return errors


def assert_valid_genome(genome_dir: Path) -> None:
    errs = validate_genome_dir(genome_dir)
    if errs:
        raise GenomeValidationError(errs)
