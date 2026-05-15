#!/usr/bin/env python3
"""Render ``app.yaml`` from ``app.yaml.template`` + the env exported
by ``scripts/deploy.config.sh``.

Called by ``scripts/deploy.sh`` immediately before
``databricks bundle deploy``. Uses ``string.Template.substitute`` (not
``safe_substitute``) so a missing variable fails loudly instead of
silently shipping a literal ``${FOO}`` to Databricks Apps.

Optional env-var entries
------------------------
Any ``env`` block item whose ``value`` renders to an empty string is
**removed from the output** so that Databricks Apps never sees it.
This prevents a stale value from a previous deploy persisting when the
operator later clears the override.  Mark optional entries with an
inline comment ``# optional`` on the ``- name:`` line:

    - name: ONTOBRICKS_SYNC_UC_CATALOG  # optional
      value: "${APP_SYNC_UC_CATALOG}"

Any item *without* the ``# optional`` tag that renders to an empty
string is left as-is (so required vars that happen to be empty still
produce a validation error at runtime rather than being silently
omitted).
"""

from __future__ import annotations

import os
import re
import string
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "app.yaml.template"
OUTPUT_PATH = REPO_ROOT / "app.yaml"

# Matches a 2-line optional env-var block:
#   - name: FOO  # optional
#     value: ""
# The value must be an empty string (after substitution).
_OPTIONAL_EMPTY_RE = re.compile(
    r"[ \t]*- name:[ \t]+\S+[ \t]+#[ \t]*optional\n"
    r"[ \t]+value:[ \t]*[\"']{0,1}[\"']{0,1}[ \t]*\n",
)


def _strip_empty_optional(text: str) -> tuple[str, list[str]]:
    """Remove optional env-var entries whose value is empty.

    Returns the cleaned text and a list of removed variable names for
    logging.
    """
    removed: list[str] = []

    def _sub(m: re.Match) -> str:
        name_match = re.search(r"- name:[ \t]+(\S+)", m.group(0))
        if name_match:
            removed.append(name_match.group(1))
        return ""

    cleaned = _OPTIONAL_EMPTY_RE.sub(_sub, text)
    return cleaned, removed


def main() -> int:
    if not TEMPLATE_PATH.exists():
        print(f"ERROR: missing {TEMPLATE_PATH}", file=sys.stderr)
        return 1

    template = string.Template(TEMPLATE_PATH.read_text())
    try:
        rendered = template.substitute(os.environ)
    except KeyError as exc:
        print(
            f"ERROR: app.yaml.template references ${{{exc.args[0]}}} but the "
            "variable is not set. Add it to scripts/deploy.config.sh or "
            f"export it before running deploy.",
            file=sys.stderr,
        )
        return 2
    except ValueError as exc:
        print(f"ERROR: malformed placeholder in template: {exc}", file=sys.stderr)
        return 3

    rendered, omitted = _strip_empty_optional(rendered)
    for name in omitted:
        print(f"  omitted empty optional env var: {name}")

    OUTPUT_PATH.write_text(rendered)
    print(f"  rendered {OUTPUT_PATH.relative_to(REPO_ROOT)} from "
          f"{TEMPLATE_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
