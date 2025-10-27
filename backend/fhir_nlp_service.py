"""
Refactored FHIR NLP service for Medblocks Demo Server
- Adds intelligent fallback for unsupported SNOMED code searches
- Gracefully handles HTTP 400/404 with retry using text-based search
- Summarizes patient data (name, gender, age, conditions)
- Clean structured JSON response for frontend table display
"""

import os
import re
import logging
from datetime import date
from typing import Dict, Any, List
from urllib.parse import urlencode

from flask import Flask, request, jsonify
from flask_cors import CORS
import spacy
from spacy.pipeline import EntityRuler
from fhirpy import SyncFHIRClient
import requests

# -----------------------
# Logging setup
# -----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fhir_nlp_service")

# -----------------------
# Config
# -----------------------
FHIR_BASE = os.environ.get("FHIR_BASE", "http://fhir-bootcamp.medblocks.com/fhir")
FHIR_AUTH = os.environ.get("FHIR_AUTH")

# Known working SNOMED codes on Medblocks demo server
CONDITION_MAP = {
    "hypertension": {"term": "Hypertension", "code": "38341003", "system": "http://snomed.info/sct"},
    "hypercholesterolemia": {"term": "Hypercholesterolemia", "code": "55822004", "system": "http://snomed.info/sct"},
    "burn": {"term": "Burn", "code": "39065001", "system": "http://snomed.info/sct"},
    "diabetes": {"term": "Diabetes", "code": "44054006", "system": "http://snomed.info/sct"},
}

client = SyncFHIRClient(FHIR_BASE)
if FHIR_AUTH:
    client.server.session.headers.update({"Authorization": FHIR_AUTH})

# -----------------------
# NLP setup
# -----------------------
nlp = spacy.load("en_core_web_sm")
patterns = [
    {"label": "AGE_MAX", "pattern": [{"LOWER": "under"}, {"IS_DIGIT": True}]},
    {"label": "AGE_MIN", "pattern": [{"LOWER": "over"}, {"IS_DIGIT": True}]},
    {"label": "GENDER", "pattern": [{"LOWER": "female"}]},
    {"label": "GENDER", "pattern": [{"LOWER": "male"}]},
]
for key in CONDITION_MAP.keys():
    patterns.append({"label": "CONDITION", "pattern": [{"LOWER": token} for token in key.split()]})
ruler = nlp.add_pipe("entity_ruler", before="ner")
ruler.add_patterns(patterns)


# -----------------------
# Helpers
# -----------------------
def subtract_years(from_date: date, years: int) -> date:
    try:
        return from_date.replace(year=from_date.year - years)
    except ValueError:
        return from_date.replace(month=2, day=28, year=from_date.year - years)


def build_search_url(resource: str, params: Dict[str, str]) -> str:
    return f"{FHIR_BASE.rstrip('/')}/{resource}?" + urlencode(params)


# -----------------------
# NLP parser
# -----------------------
def parse_query(query: str) -> Dict[str, Any]:
    doc = nlp(query)
    filters = {"age_min": None, "age_max": None, "gender": None, "conditions": []}
    q_lower = query.lower()

    for ent in doc.ents:
        if ent.label_ == "AGE_MAX":
            m = re.search(r"(\d{1,3})", ent.text)
            if m:
                filters["age_max"] = int(m.group(1))
        elif ent.label_ == "AGE_MIN":
            m = re.search(r"(\d{1,3})", ent.text)
            if m:
                filters["age_min"] = int(m.group(1))
        elif ent.label_ == "GENDER":
            filters["gender"] = ent.text.lower()
        elif ent.label_ == "CONDITION":
            cond = CONDITION_MAP.get(ent.text.lower())
            if cond:
                filters["conditions"].append(cond.copy())

    # fallback scan
    if not filters["conditions"]:
        for key, val in CONDITION_MAP.items():
            if key in q_lower:
                filters["conditions"].append(val.copy())

    return filters


# -----------------------
# Smart Condition Query
# -----------------------
def safe_condition_query(code: str, term: str) -> Dict[str, Any]:
    """Try SNOMED code search, fallback to text search."""
    try:
        url = f"{FHIR_BASE.rstrip('/')}/Condition?code=http://snomed.info/sct|{code}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
        logger.warning(f"Code search failed ({r.status_code}), trying text fallback...")
        fallback_url = f"{FHIR_BASE.rstrip('/')}/Condition?code:text={term}"
        r2 = requests.get(fallback_url, timeout=10)
        return r2.json() if r2.status_code == 200 else {"error": f"Both searches failed ({r.status_code}/{r2.status_code})"}
    except Exception as e:
        return {"error": str(e)}


# -----------------------
# Main Query Logic
# -----------------------
def query_fhir(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Robust query logic:
    - Use safe_condition_query to get Condition bundle (dict)
    - Extract patient ids (handles Patient/<id> and urn:uuid:<id> forms)
    - Batch fetch Patient resources via fhirpy search(_id=...)
    - Apply gender/age filters client-side
    - Summarize patients for UI
    """
    out = {
        "filters": filters,
        "fhir_queries": {},
        "patients": [],
        "errors": [],
        "debug": {},
    }

    try:
        condition_results = None
        patient_ids = set()

        # 1) Condition search (use conditions from filters)
        if filters.get("conditions"):
            # we currently only take first condition to keep behavior predictable
            for cond in filters["conditions"]:
                code = cond.get("code")
                term = cond.get("term")
                # record intended search URL for debugging
                out["fhir_queries"]["condition_code_query"] = f"{FHIR_BASE.rstrip('/')}/Condition?code={code}"
                # safe_condition_query will try code search then fallback to text search
                condition_results = safe_condition_query(code, term)
                out["debug"]["condition_results_total"] = (condition_results.get("total") if isinstance(condition_results, dict) else None)

                # extract patient references
                entries = condition_results.get("entry", []) if isinstance(condition_results, dict) else []
                for entry in entries:
                    subj = entry.get("resource", {}).get("subject", {})
                    if not subj:
                        continue
                    ref = subj.get("reference") or subj.get("id") or ""
                    if not ref:
                        continue
                    # normalize and extract id
                    # formats might be: "Patient/<id>", "patient/<id>", "urn:uuid:<id>"
                    ref_lower = ref.lower()
                    pid = None
                    if ref_lower.startswith("patient/"):
                        pid = ref.split("/", 1)[1]
                    elif "urn:uuid:" in ref_lower:
                        pid = ref.split(":", 2)[-1]
                    else:
                        # fallback: if there is a slash, take last part
                        if "/" in ref:
                            pid = ref.split("/")[-1]
                        else:
                            pid = ref
                    if pid:
                        patient_ids.add(pid)

        # 2) Fetch patient resources in batch if we have ids
        fetched_patients = []
        if patient_ids:
            ids_csv = ",".join(patient_ids)
            out["fhir_queries"]["patient_batch_query"] = f"{FHIR_BASE.rstrip('/')}/Patient?_id={ids_csv}"
            try:
                # fhirpy .search(_id=...) typically returns a dict with 'entry' for public HAPI servers
                patient_search_res = client.resources("Patient").search(_id=ids_csv).fetch()
                # patient_search_res might be a dict (bundle) or a list depending on fhirpy; handle both
                if isinstance(patient_search_res, dict) and "entry" in patient_search_res:
                    for entry in patient_search_res["entry"]:
                        r = entry.get("resource")
                        if r and r.get("resourceType") == "Patient":
                            fetched_patients.append(r)
                elif isinstance(patient_search_res, list):
                    # fhirpy sometimes returns a list of resource dicts
                    for r in patient_search_res:
                        if isinstance(r, dict) and r.get("resourceType") == "Patient":
                            fetched_patients.append(r)
                else:
                    # unexpected structure; record for debugging
                    out["debug"]["patient_search_raw"] = patient_search_res
            except Exception as e:
                logger.exception("Batch patient fetch failed")
                out["errors"].append(f"Batch patient fetch failed: {str(e)}")

        else:
            # If no patient ids (no condition or condition had no subject refs),
            # fall back to searching by patient-level filters (birthdate/gender)
            # or fetch a small sample (limit) to avoid huge downloads.
            patient_search_params = {}
            # apply birthdate filters if age_min/age_max provided
            today = date.today()
            if filters.get("age_min") is not None:
                bd = subtract_years(today, filters["age_min"])
                patient_search_params["birthdate"] = f"le{bd.isoformat()}"
            if filters.get("age_max") is not None:
                bd = subtract_years(today, filters["age_max"])
                existing = patient_search_params.get("birthdate")
                if existing:
                    patient_search_params["birthdate"] = existing + "," + f"ge{bd.isoformat()}"
                else:
                    patient_search_params["birthdate"] = f"ge{bd.isoformat()}"
            if filters.get("gender"):
                patient_search_params["gender"] = filters["gender"]

            if patient_search_params:
                out["fhir_queries"]["patient_search_params"] = patient_search_params
                try:
                    patient_search_res = client.resources("Patient").search(**patient_search_params).fetch()
                    if isinstance(patient_search_res, dict) and "entry" in patient_search_res:
                        for entry in patient_search_res["entry"]:
                            r = entry.get("resource")
                            if r and r.get("resourceType") == "Patient":
                                fetched_patients.append(r)
                except Exception as e:
                    logger.exception("Patient search by params failed")
                    out["errors"].append(f"Patient search by params failed: {str(e)}")
            else:
                # finally, fallback: fetch a small set
                try:
                    patient_search_res = client.resources("Patient").search(_count=10).fetch()
                    if isinstance(patient_search_res, dict) and "entry" in patient_search_res:
                        for entry in patient_search_res["entry"]:
                            r = entry.get("resource")
                            if r and r.get("resourceType") == "Patient":
                                fetched_patients.append(r)
                except Exception as e:
                    out["errors"].append(f"Default patient fetch failed: {str(e)}")

        out["debug"]["patient_ids_found"] = list(patient_ids)
        out["debug"]["fetched_patients_count"] = len(fetched_patients)

        # 3) Client-side filtering (apply gender and age filters)
        def patient_matches_filters(p):
            # gender
            if filters.get("gender"):
                g = filters["gender"].lower()
                if (p.get("gender") or "").lower() != g:
                    return False
            # age
            age_min = filters.get("age_min")
            age_max = filters.get("age_max")
            if (age_min is not None) or (age_max is not None):
                # compute age from birthDate if possible
                bd = p.get("birthDate")
                if not bd:
                    return False
                try:
                    by = int(bd.split("-")[0])
                    age = date.today().year - by
                except Exception:
                    return False
                if age_min is not None and age < age_min:
                    return False
                if age_max is not None and age > age_max:
                    return False
            return True

        filtered_patients = [p for p in fetched_patients if patient_matches_filters(p)]

        # 4) Summarize patients with attached condition names (from condition_results)
        summarized = []
        for p in filtered_patients:
            pid = p.get("id", "")
            # Name extraction (safe)
            name = ""
            if p.get("name") and isinstance(p["name"], list) and p["name"]:
                n0 = p["name"][0]
                given = (n0.get("given") and n0.get("given")[0]) or ""
                family = n0.get("family") or ""
                name = f"{given} {family}".strip()
            elif p.get("name") and isinstance(p.get("name"), str):
                name = p.get("name")
            else:
                name = pid

            birthDate = p.get("birthDate", "")
            age = None
            if birthDate:
                try:
                    year = int(birthDate.split("-")[0])
                    age = date.today().year - year
                except Exception:
                    age = None

            # find condition text entries that reference this patient
            cond_texts = []
            if isinstance(condition_results, dict) and condition_results.get("entry"):
                for entry in condition_results["entry"]:
                    res = entry.get("resource", {})
                    subj_ref = res.get("subject", {}).get("reference", "")
                    # normalize subj_ref forms
                    if subj_ref.endswith(pid) or subj_ref == f"Patient/{pid}" or subj_ref.endswith(f":{pid}"):
                        # try to get display text for code
                        code_text = ""
                        codefield = res.get("code", {})
                        if isinstance(codefield.get("text"), str) and codefield.get("text").strip():
                            code_text = codefield.get("text").strip()
                        elif isinstance(codefield.get("coding"), list) and codefield.get("coding"):
                            code_text = codefield.get("coding")[0].get("display", "")
                        if code_text:
                            cond_texts.append(code_text)

            summarized.append({
                "id": pid,
                "name": name,
                "gender": p.get("gender", ""),
                "birthDate": birthDate,
                "age": age,
                "conditions": cond_texts
            })

        out["patients"] = summarized

    except Exception as e:
        logger.exception("Unexpected error in query_fhir")
        out["errors"].append(str(e))

    return out


# -----------------------
# Flask App
# -----------------------
app = Flask(__name__)
CORS(app)


@app.route("/interpret", methods=["POST"])
def interpret():
    body = request.get_json(force=True)
    query = body.get("query", "")
    if not query:
        return jsonify({"error": "Empty query"}), 400

    filters = parse_query(query)
    results = query_fhir(filters)

    return jsonify({
        "query": query,
        "filters": filters,
        "fhir_queries": results.get("fhir_queries"),
        "patients": results.get("patients"),
        "errors": results.get("errors"),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
