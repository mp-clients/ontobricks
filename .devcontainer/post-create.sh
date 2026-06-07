#!/usr/bin/env bash
# postCreateCommand — runs once per "Rebuild Container". Idempotent.
set -euo pipefail

# The persisted login volumes mount root-owned on first create; hand them to the
# container user so the CLIs can write credentials. This is what lets you log in once
# and have it stick across rebuilds (and shared across projects via the volumes).
# ~/.claude = Claude Code credential; ~/.config/gh = GitHub CLI auth.
echo "==> Ensure persisted login volumes are owned by the container user"
sudo chown -R "$(id -un):$(id -gn)" "$HOME/.claude" 2>/dev/null || true
sudo chown -R "$(id -un):$(id -gn)" "$HOME/.config/gh" 2>/dev/null || true

echo "==> Claude Code CLI (global)"
npm install -g @anthropic-ai/claude-code

echo "==> uv (Python package/tool manager — repo uses uv.lock)"
pipx install uv || pip install --user uv

# --- repo-specific setup ---
echo "==> Sync project dependencies from uv.lock"
uv sync

# --- Graphify: knowledge-graph skill, scoped to THIS project only ---
# CLI installed inside the container (never on the host), skill written into the
# repo's own .claude/skills so it stays project-local and commit-able.
echo "==> Install Graphify CLI (PyPI package 'graphifyy', CLI 'graphify')"
# pipx puts the shim in the image's /usr/local/py-utils/bin (already on PATH).
pipx install graphifyy

echo "==> Register the graphify skill into this project (.claude/skills/graphify/)"
graphify install --project

echo "==> Done. Run \`claude\` and \`gh auth login\` once; both persist across rebuilds."
echo "    Then use /graphify inside Claude Code to build/query the knowledge graph."
