import pathlib

DEAD_NAMES = ("TypedBaseItems", "PlaylistItems")


def test_no_pre_4_9_table_names_in_src():
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "emby_mcp"
    offenders = []
    for path in src.rglob("*.py"):
        if path.name == "schema.py":  # documents the rename intentionally
            continue
        text = path.read_text(encoding="utf-8")
        for dead in DEAD_NAMES:
            if dead in text:
                offenders.append(f"{path.name}: {dead}")
    assert not offenders, f"pre-4.9 table names still present: {offenders}"
