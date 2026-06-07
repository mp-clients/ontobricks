# CLAUDE.md — Operating Contract for OntoBricks

> **Single source of truth.** All project conventions live in `.cursor/*.mdc`,
> `.cursorrules`, and `src/.coding_rules.md`. Cursor reads them natively;
> Claude Code reads them via the `@`-import syntax below. **Do not duplicate
> rules in this file** — edit the canonical files instead.

## Imported canonical rules

The `@./path` syntax tells Claude Code to recursively inline these files into
the session context. The YAML frontmatter on `.mdc` files is treated as
descriptive text and can be safely ignored when reading.

@./.cursorrules
@./.cursor/01-expertise-and-principles.mdc
@./.cursor/02-project-overview.mdc
@./.cursor/03-system-components-and-requirements.mdc
@./.cursor/04-project-structure.mdc
@./.cursor/05-code-style-and-structure.mdc
@./.cursor/06-performance-optimization.mdc
@./.cursor/07-project-conventions.mdc
@./.cursor/08-testing-and-deployment.mdc
@./.cursor/09-package-management.mdc
@./.cursor/10-entity-panel-matrix.mdc
@./.cursor/11-frontend-design.mdc
@./src/.coding_rules.md

## Claude-only additions

Everything below is **Claude-Code-specific** and has no Cursor equivalent. It
does not duplicate the canonical rules — it only tells Claude how to use its
own tooling (skills, mode switches) on top of those rules.

### Skills (auto-invoked by description)

| Skill | Trigger phrases |
|-------|-----------------|
| `code-review` | "code review", "review the code", reviewing a feature/PR/branch |
| `refactoring` | "refactor", restructure, clean up, simplify, deduplicate |
| `changelog` | After **any** code change (mandatory post-step from `.cursorrules`) |
| `deploy` | "deploy", "ship", "release" to Databricks |
| `adding-subpackage` | New subdir under `back/core/`, `back/objects/`, or `agents/` |

The skill files in `.claude/skills/<name>/SKILL.md` are themselves thin —
they sequence the work and point back to the canonical rules. They do not
restate the rules.

### Databricks-related work

For Databricks workspace deploys, queries, Lakebase, Apps, Asset Bundles,
authentication, or Unity Catalog operations, the user has the `fe-vibe` and
`databricks-skills` plugin skills available via the `Skill` tool. Prefer
those over reinventing.

### Tone

Per `.cursor/01-expertise-and-principles.mdc §Personal Style`: casual, terse,
expert-to-expert. Answer first, explanation after. Don't repeat the user's
file when showing an edit — show changed lines plus a couple before/after.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
