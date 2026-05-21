"""
Shared AST safety rules — imported by both:
  - infrastructure/validators/python_validators.py  (host-side pre-validation)
  - infrastructure/sandbox_entry.py                 (container-side defence-in-depth)

Keeping one source of truth prevents the two layers from drifting apart.
"""
import ast

FORBIDDEN_NODES = (
    ast.Import,
    ast.ImportFrom,
)

FORBIDDEN_NAMES: frozenset[str] = frozenset({
    "exec", "eval", "compile", "execfile",
    "open", "file", "input",
    "os", "sys", "subprocess", "shutil",
    "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr",
    "breakpoint", "exit", "quit",
    "__import__", "__builtins__", "__loader__",
    "__spec__", "__name__", "__file__",
})
