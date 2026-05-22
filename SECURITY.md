# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.4.x   | ✅ Active support |
| 0.3.x   | ⚠️ Critical fixes only |
| < 0.3.0 | ❌ No longer supported |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues by emailing **security@databricks.com** with the subject line:
`[OntoBricks] Security Vulnerability Report`

Include:
- Description of the vulnerability and its potential impact
- Steps to reproduce (proof-of-concept or detailed description)
- Affected versions
- Any suggested mitigations or patches

### Response Timeline

| Milestone | Target |
|-----------|--------|
| Acknowledgement | 48 hours |
| Initial triage | 5 business days |
| Fix for Critical/High | 30 days |
| Fix for Medium/Low | 90 days |
| Public disclosure | After fix is released |

We follow coordinated disclosure: once a fix is available we will publish a GitHub Security Advisory and request a CVE if applicable.

## Dependency Vulnerability Management

OntoBricks uses `pip-audit` in CI to scan all Python dependencies for known CVEs before every merge and release. Critical and High severity issues must be resolved before a marketplace publication is approved.

Dependabot is configured to open weekly PRs for both Python (`pip`) and GitHub Actions dependencies.

Known constraints applied to transitive dependencies are tracked in the `[tool.uv].constraint-dependencies` section of `pyproject.toml` with inline comments referencing the CVE/GHSA identifiers.

## Scope

This policy covers the OntoBricks application code hosted at
[github.com/databrickslabs/ontobricks](https://github.com/databrickslabs/ontobricks).

Issues in upstream dependencies (Databricks SDK, FastAPI, rdflib, etc.) should be reported
to the respective upstream project maintainers. We will apply mitigating constraints or
version pins as needed.
