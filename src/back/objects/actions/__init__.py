"""Kinetic Action layer — typed, validated, audited, reversible Actions
that mutate ontology state through a single ActionService seam.

Action Types are code-registered today (see ``registry``); the registry is
designed to later load definitions from ontology metadata (north-star B)
without changing ActionService, the overlay, the audit log, or effects.
"""
