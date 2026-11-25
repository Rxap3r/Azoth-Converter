"""Error messages, tooltips, notes and help texts follow the app's writing rules: the style
of Simplified Technical English (ASD-STE100), see CLAUDE.md → "Writing messages"."""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "azoth"
INTERNAL = {"ValueError", "KeyError", "TypeError", "RuntimeError", "UnpicklingError"}
NOTES = re.compile(r"_(NOTE|CHOICES)$|^(TEXT_ONLY|QUALITY_NOTE|CHOICES)$")
NOT_ALLOWED = re.compile(r"n't\b|\bCould not\b|\bcould not\b|\bPlease\b|\bplease\b")
# Words STE100 (Issue 9) does not approve, with the approved words to use. Checked
# against the STE word list; "size" and computer verbs (save, delete, convert …) are
# technical words and allowed.
REJECTED = {
    "already": "(leave out)", "another": "a different", "any": "one, all", "big": "large",
    "bigger": "larger", "enlarge": "make larger", "every": "each, all", "exact": "accurate",
    "exactly": "accurately", "fail": "cannot …", "failed": "cannot …", "fails": "cannot …",
    "fine": "small, good", "instead": "(rephrase)", "inside": "in", "little": "small",
    "may": "can, possibly", "need": "necessary", "needs": "necessary", "never": "do not",
    "normal": "usual", "real": "correct", "several": "some", "sideways": "on its side",
    "whole": "full, all", "works": "operates, (rephrase)", "wrong": "incorrect",
    "visible": "that you can see", "choice": "selection", "takes": "(rephrase)",
}  # fmt: skip


def _text(node) -> str:
    """The words of a string expression (f-string parts and implicit concatenation)."""
    return " ".join(
        part.value
        for part in ast.walk(node)
        if isinstance(part, ast.Constant) and isinstance(part.value, str)
    )


def _user_texts():
    """(place, text) of each error message, tooltip, note and help text."""
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            found = []
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                name = getattr(node.exc.func, "id", getattr(node.exc.func, "attr", ""))
                if name not in INTERNAL:
                    found.append(node.exc.args[0])
            elif isinstance(node, ast.Call):
                if getattr(node.func, "attr", "") == "setToolTip" and node.args:
                    found.append(node.args[0])
                found += [kw.value for kw in node.keywords if kw.arg == "help"]
            elif isinstance(node, ast.FunctionDef) and node.name in (
                "quality_note",
                "unavailable_reason",
            ):
                found += [r.value for r in ast.walk(node) if isinstance(r, ast.Return) and r.value]
            elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and NOTES.search(t.id) for t in node.targets
            ):
                found.append(node.value)
            for value in found:
                yield f"{path.relative_to(SRC)}:{value.lineno}", _text(value)


def test_texts_have_no_short_forms_or_please():
    found = [f"{place}: {text!r}" for place, text in _user_texts() if NOT_ALLOWED.search(text)]
    assert not found, "\n".join(found)


def test_texts_use_ste_words():
    found = []
    for place, text in _user_texts():
        for word in re.findall(r"[A-Za-z]+", text):
            if word.lower() in REJECTED and not word.isupper():
                found.append(f"{place}: “{word}” → {REJECTED[word.lower()]}")
    assert not found, "\n".join(found)


def test_the_check_finds_the_texts():
    assert sum(1 for _ in _user_texts()) > 200  # the check really looks at the texts
