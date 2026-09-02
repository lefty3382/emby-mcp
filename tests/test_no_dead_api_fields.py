"""Guard against reading REST/DB fields Emby 4.9 no longer provides.

Sibling of test_no_dead_tables.py: that one guards dead *table* names,
this one guards dead *field* names. Reading an absent key is silent —
.get() returns None — so these only surface as permanently-null output.
"""

import ast
import io
import pathlib
import re
import tokenize

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "emby_mcp"

# /System/Info in Emby 4.9.5 returns none of these.
# LocalAddress/WanAddress became the LocalAddresses/RemoteAddresses arrays.
DEAD_API_FIELDS = (
    "SupportsAutoRunAtStartup",  # a startup-service flag, never a Premiere flag
    "ProgramDataPath",
    "ItemsByNamePath",
    "LocalAddress",
    "WanAddress",
)

# LocalUsersv2 is (Id INTEGER, guid GUID, data BLOB) — user attributes live
# inside the BLOB, so selecting columns by these names yields only nulls.
DEAD_USER_COLUMNS = ("ConnectUserName", "ConnectUserId", "EasyPassword")


def _code_only(text: str) -> str:
    """Strip comments and docstrings so prose about dead fields is not a hit.

    These names must stay writable in explanatory docstrings — the point is to
    catch code that *reads* them, not documentation that warns against it.
    """
    tree = ast.parse(text)
    doc_spans = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                doc_spans.update(range(first.lineno, first.end_lineno + 1))

    lines = []
    for i, line in enumerate(text.splitlines(), start=1):
        lines.append("" if i in doc_spans else line)
    stripped = "\n".join(lines)

    out = []
    for tok in tokenize.generate_tokens(io.StringIO(stripped).readline):
        if tok.type != tokenize.COMMENT:
            out.append(tok.string)
    return "\n".join(out)


def _sources():
    return [(p, _code_only(p.read_text(encoding="utf-8"))) for p in SRC.rglob("*.py")]


def test_no_dead_system_info_fields():
    offenders = []
    for path, code in _sources():
        for dead in DEAD_API_FIELDS:
            if re.search(rf"\b{dead}\b", code):
                offenders.append(f"{path.name}: {dead}")
    assert not offenders, f"fields absent from Emby 4.9 /System/Info: {offenders}"


def test_local_usersv2_is_not_queried_for_attribute_columns():
    offenders = []
    for path, code in _sources():
        if "LocalUsersv2" not in code:
            continue
        for dead in DEAD_USER_COLUMNS:
            if re.search(rf"\b{dead}\b", code):
                offenders.append(f"{path.name}: {dead}")
    assert not offenders, (
        f"LocalUsersv2 has no such columns (data is a BLOB): {offenders}"
    )


def test_local_usersv2_is_never_select_starred():
    """SELECT * returns Id/guid/data only — never the user attributes."""
    offenders = [
        path.name
        for path, code in _sources()
        if re.search(r"SELECT\s+\*\s+FROM\s+LocalUsersv2", code, re.I)
    ]
    assert not offenders, f"SELECT * FROM LocalUsersv2 cannot yield user fields: {offenders}"
