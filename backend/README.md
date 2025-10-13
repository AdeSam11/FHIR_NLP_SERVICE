## backend/fhir_nlp_service.py

Real FHIR-backed NLP -> FHIR query translator.

Environment variables (or config):
 - FHIR_BASE: base URL of FHIR server, e.g., https://hapi.fhir.org/baseR4
 - FHIR_AUTH: optional bearer token (set as "Bearer <token>") or None

Run:
 export FHIR_BASE=https://hapi.fhir.org/baseR4
 python backend/fhir_nlp_service.py
