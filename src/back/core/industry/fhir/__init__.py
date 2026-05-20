"""HL7 FHIR import service (multi-version: R4, R4B, R5)."""

from back.core.industry.fhir.FhirImportService import FhirImportService

get_fhir_catalog = FhirImportService.get_fhir_catalog
get_fhir_versions = FhirImportService.get_fhir_versions
fetch_and_parse_fhir = FhirImportService.fetch_and_parse_fhir

__all__ = [
    "FhirImportService",
    "get_fhir_catalog",
    "get_fhir_versions",
    "fetch_and_parse_fhir",
]
