"""The architecture's rules, enforced by reading the code.

ARCHITECTURE.md states a dependency direction and a no-PHI-in-logs rule;
prose erodes, so this test reads every module under src/ with `ast` and
fails on a violation. No dependency beyond the standard library.

Rules:

1. records/ imports only the standard library and records.
2. The port modules (workflow/ports.py, workflow/events.py: the
   contracts adapters implement) import only the standard library,
   records, and each other.
3. Each adapter (adapters/<system>/) imports only third-party packages,
   records, the port modules, and its own package: never the rest of the
   workflow, another adapter, or runtime.
4. workflow/ imports only the standard library, records, and workflow:
   no adapter, no third-party package. policy.py and periods.py, the
   pure decider and the period fold, import only the standard library
   and records.
5. Only runtime/ imports runtime.
6. Only runtime/ reads the environment or the clock (os.environ,
   os.getenv, datetime.now, time.sleep, time.monotonic): everything else
   receives them, which is what makes it testable.
7. No exception value reaches a log line or an f-string: inside
   `except ... as e`, `e` may be inspected (`type(e).__name__`,
   `e.status_code`, `isinstance`), never logged or interpolated whole;
   `logger.exception(...)` and `exc_info=` are banned outright. Messages
   can carry response bodies or field values; classes cannot.

ALLOWED is a ratchet for any exception that must exist temporarily, each
named; a stale entry fails the test, so it can only shrink. It is empty.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = "mn_immunization"
SRC = Path(__file__).resolve().parents[1] / "src" / PACKAGE

PORT_MODULES = {f"{PACKAGE}.workflow.ports", f"{PACKAGE}.workflow.events"}
PURE_MODULES = {
    f"{PACKAGE}.workflow.policy",
    f"{PACKAGE}.workflow.periods",
}
"""The decider and the period key: standard library and records only.
(history.py also folds events, so it may import the event vocabulary.)"""
CLOCK_AND_ENV = {
    ("os", "environ"),
    ("os", "getenv"),
    ("datetime", "now"),
    ("time", "sleep"),
    ("time", "monotonic"),
}
LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception", "log"}

ALLOWED: set[str] = set()


def module_name(path: Path) -> str:
    relative = path.relative_to(SRC.parent).with_suffix("")
    return ".".join(relative.parts)


def slice_of(module: str) -> str:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else ""


def adapter_of(module: str) -> str:
    """The external system an adapter module belongs to (adapters/<it>/)."""
    parts = module.split(".")
    return parts[2] if len(parts) > 2 and parts[1] == "adapters" else ""


def is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


def is_ours(module: str) -> bool:
    return module == PACKAGE or module.startswith(f"{PACKAGE}.")


def imported_modules(tree: ast.AST, module: str) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")[: -node.level]
                target = ".".join([*base, node.module] if node.module else base)
            else:
                target = node.module or ""
            for alias in node.names:
                # `from package import submodule` imports the submodule.
                candidate = f"{target}.{alias.name}"
                found.add(candidate if _is_our_module(candidate) else target)
    return found


def _is_our_module(dotted: str) -> bool:
    if not is_ours(dotted):
        return False
    path = SRC.parent.joinpath(*dotted.split("."))
    return path.with_suffix(".py").exists() or path.is_dir()


def import_violations(module: str, imports: set[str]) -> set[str]:
    violations = set()
    here = slice_of(module)
    for target in imports:
        if is_stdlib(target):
            continue
        ours = is_ours(target)
        there = slice_of(target) if ours else ""
        is_port = target in PORT_MODULES
        if here == "records":
            ok = ours and there == "records"
        elif module in PORT_MODULES:
            ok = ours and (there == "records" or is_port)
        elif here == "adapters":
            same = adapter_of(target) == adapter_of(module)
            ok = not ours or there == "records" or is_port or same
        elif module in PURE_MODULES:
            ok = ours and there == "records"
        elif here == "workflow":
            ok = ours and there in ("records", "workflow")
        else:
            ok = True
        if ours and there == "runtime" and here != "runtime":
            ok = False
        if not ok:
            violations.add(f"{module} imports {target}")
    return violations


def clock_and_env_violations(tree: ast.AST, module: str) -> set[str]:
    if slice_of(module) == "runtime":
        return set()
    violations = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and (node.value.id, node.attr) in CLOCK_AND_ENV
        ):
            violations.add(f"{module} uses {node.value.id}.{node.attr}")
    return violations


def _is_logger_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in LOG_METHODS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in ("logger", "logging", "log")
    )


def _whole_value_uses(node: ast.AST, name: str, parents: dict) -> list[ast.Name]:
    """Uses of `name` that pass the exception itself along, as opposed to
    inspecting it: type(e), e.attr, isinstance(e, ...), getattr(e, ...)."""
    uses = []
    for child in ast.walk(node):
        if not (isinstance(child, ast.Name) and child.id == name):
            continue
        parent = parents.get(child)
        if isinstance(parent, ast.Attribute):
            continue
        if (
            isinstance(parent, ast.Call)
            and isinstance(parent.func, ast.Name)
            and parent.func.id in ("type", "isinstance", "getattr", "hasattr")
            and parent.args
            and parent.args[0] is child
        ):
            continue
        uses.append(child)
    return uses


def phi_violations(tree: ast.AST, module: str) -> set[str]:
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    violations = set()
    for node in ast.walk(tree):
        if _is_logger_call(node):
            if node.func.attr == "exception":
                violations.add(f"{module} calls logger.exception")
            if any(kw.arg == "exc_info" for kw in node.keywords):
                violations.add(f"{module} logs exc_info")
        if not (isinstance(node, ast.ExceptHandler) and node.name):
            continue
        for inner in ast.walk(node):
            leaks = False
            if _is_logger_call(inner):
                args = [*inner.args, *(kw.value for kw in inner.keywords)]
                leaks = any(_whole_value_uses(arg, node.name, parents) for arg in args)
            elif isinstance(inner, ast.JoinedStr):
                leaks = bool(_whole_value_uses(inner, node.name, parents))
            elif (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id in ("str", "repr")
            ):
                leaks = bool(_whole_value_uses(inner, node.name, parents))
            if leaks:
                violations.add(
                    f"{module} puts exception value {node.name!r} in a message"
                )
    return violations


def all_violations() -> set[str]:
    violations = set()
    for path in sorted(SRC.rglob("*.py")):
        module = module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations |= import_violations(module, imported_modules(tree, module))
        violations |= clock_and_env_violations(tree, module)
        violations |= phi_violations(tree, module)
    return violations


def test_no_new_violations():
    new = sorted(all_violations() - ALLOWED)
    assert not new, "architecture rules broken:\n  " + "\n  ".join(new)


def test_allowed_list_only_shrinks():
    fixed = sorted(ALLOWED - all_violations())
    assert not fixed, (
        "these ALLOWED entries no longer occur; delete them:\n  " + "\n  ".join(fixed)
    )


# --- the checker checks itself on small samples ---


def _phi(source: str) -> set[str]:
    return phi_violations(ast.parse(source), "sample")


def test_checker_flags_a_logged_exception():
    flagged = _phi(
        "try:\n    pass\nexcept Exception as error:\n"
        "    logger.error('failed: %s', error)\n"
    )
    assert flagged == {"sample puts exception value 'error' in a message"}


def test_checker_flags_an_interpolated_exception():
    flagged = _phi(
        "try:\n    pass\nexcept Exception as e:\n    raise ValueError(f'bad {e}')\n"
    )
    assert flagged


def test_checker_allows_class_and_attributes():
    assert not _phi(
        "try:\n    pass\nexcept Exception as error:\n"
        "    logger.error('%s %s', type(error).__name__, error.status_code)\n"
        "    logger.error('%s', getattr(error, 'status_code', None))\n"
        "    raise RuntimeError('x') from error\n"
    )


def test_checker_flags_logger_exception_and_exc_info():
    assert _phi("logger.exception('boom')\n") == {"sample calls logger.exception"}
    assert _phi("logger.error('boom', exc_info=True)\n") == {"sample logs exc_info"}


def test_checker_flags_the_workflow_reaching_an_adapter():
    imports = {f"{PACKAGE}.adapters.gcs.storage", f"{PACKAGE}.workflow.ports", "json"}
    assert import_violations(f"{PACKAGE}.workflow.x", imports) == {
        f"{PACKAGE}.workflow.x imports {PACKAGE}.adapters.gcs.storage"
    }


def test_checker_keeps_adapters_apart():
    imports = {f"{PACKAGE}.adapters.gcs.storage", f"{PACKAGE}.adapters.miic.parsing"}
    assert import_violations(f"{PACKAGE}.adapters.miic.client", imports) == {
        f"{PACKAGE}.adapters.miic.client imports {PACKAGE}.adapters.gcs.storage"
    }


def test_checker_keeps_records_pure():
    assert import_violations(f"{PACKAGE}.records.x", {"requests"}) == {
        f"{PACKAGE}.records.x imports requests"
    }
