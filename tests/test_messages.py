"""Error messages follow the app's writing rules (Simplified Technical English style, see
CLAUDE.md → "Writing messages"): no contractions, "Cannot …" instead of "Could not …",
instructions start with the verb, no "please"."""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "azoth"
INTERNAL = {"ValueError", "KeyError", "TypeError", "RuntimeError", "UnpicklingError"}
NOT_ALLOWED = re.compile(r"n't\b|\bCould not\b|\bcould not\b|\bPlease\b|\bplease\b")


def _messages():
    """(place, text) of every message raised with an error the user sees."""
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            name = getattr(node.exc.func, "id", getattr(node.exc.func, "attr", ""))
            if name in INTERNAL or not node.exc.args:
                continue
            for part in ast.walk(node.exc.args[0]):
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    yield f"{path.relative_to(SRC)}:{node.lineno}", part.value


def test_error_messages_follow_the_writing_rules():
    found = [f"{place}: {text!r}" for place, text in _messages() if NOT_ALLOWED.search(text)]
    assert not found, "\n".join(found)


def test_the_check_finds_messages():
    assert sum(1 for _ in _messages()) > 100  # the check really looks at the messages
