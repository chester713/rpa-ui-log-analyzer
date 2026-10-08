"""Guard the README's Python 3.10+ claim.

Backslashes inside an f-string replacement field (e.g. f"{'\\n'.join(x)}") only
became legal in Python 3.12 (PEP 701); earlier versions raise a SyntaxError when
the module is imported. Build such strings before the f-string instead.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKSLASH = chr(92)


def _python_files() -> list[Path]:
    return [ROOT / "app.py", ROOT / "src_cli.py", *sorted((ROOT / "src").rglob("*.py"))]


def test_no_backslash_inside_fstring_replacement_fields() -> None:
    offenders = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.JoinedStr):
                continue
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    segment = ast.get_source_segment(source, part.value) or ""
                    if BACKSLASH in segment:
                        offenders.append(f"{path.relative_to(ROOT)}:{part.value.lineno}: {segment}")

    assert not offenders, "Python 3.12-only f-string syntax:\n" + "\n".join(offenders)
