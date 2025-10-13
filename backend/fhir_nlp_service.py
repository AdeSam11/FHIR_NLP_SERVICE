import os
import re
from datetime import date
from typing import Dict, Any

import requests
import spacy
from spacy.pipeline import EntityRuler
from flask import Flask, request, jsonify

# -----------------------
# Config
# -----------------------
FHIR_BASE = os.environ.get("FHIR_BASE", "https://hapi.fhir.org/baseR4")  # replace with your FHIR server
FHIR_AUTH = os.environ.get("FHIR_AUTH")  # Bearer token or None

# Example mapping - can be extended in producion
CONDITION_MAP = {
    "diabetes": {"term": "Diabetes mellitus", "code": "44054006", "system": "http://snomed.info/sct"},
    "hypertension": {"term": "Hypertensive disorder", "code": "38341003", "system": "http://snomed.info/sct"},
    "asthma": {"term": "Asthma", "code": "195967001", "system": "http://snomed.info/sct"},
}

# -----------------------
# NLP pipeline (spaCy + EntityRuler)
# -----------------------
nlp = spacy.load("en_core_web_sm")

patterns = [
    # ages
    {"label": "AGE_EXACT", "pattern": [{"LOWER": "age"}, {"IS_DIGIT": True}]},
    {"label": "AGE_EXACT", "pattern": [{"LOWER": "aged"}, {"IS_DIGIT": True}]},
    {"label": "AGE_MIN", "pattern": [{"LOWER": "older"}, {"LOWER": "than"}, {"IS_DIGIT": True}]},
    {"label": "AGE_MIN", "pattern": [{"LOWER": "over"}, {"IS_DIGIT": True}]},
    {"label": "AGE_MAX", "pattern": [{"LOWER": "under"}, {"IS_DIGIT": True}]},
    {"label": "AGE_RANGE", "pattern": [{"LOWER": "between"}, {"IS_DIGIT": True}, {"LOWER": "and"}, {"IS_DIGIT": True}]},
    # gender
    {"label": "GENDER", "pattern": [{"LOWER": "female"}]},
    {"label": "GENDER", "pattern": [{"LOWER": "male"}]},
    # conditions - simple tokens; extend for multiword conditions
]
# add a rule per key in CONDITION_MAP to boost detection
for key in CONDITION_MAP.keys():
    patterns.append({"label": "CONDITION", "pattern": [{"LOWER": token} for token in key.split()]})

# Register the entity_ruler component and get the instance back
# Using the factory name 'entity_ruler' (spaCy v3+)
ruler = nlp.add_pipe("entity_ruler", before="ner", config={"overwrite_ents": False})
ruler.add_patterns(patterns)

# -----------------------
# Helpers
# -----------------------
def subtract_years(from_date: date, years: int) -> date:
    try:
        return from_date.replace(year=from_date.year - years)
    except ValueError:
        # handle Feb 29
        return from_date.replace(month=2, day=28, year=from_date.year - years)

def build_headers():
    headers = {"Accept": "application/fhir+json"}
    if FHIR_AUTH:
        headers["Authorization"] = FHIR_AUTH
    return headers

def call_fhir(path: str, params: Dict[str, str] = None) -> Dict[str, Any]:
    """Call FHIR server and return parsed JSON. Raises on non-200."""
    url = FHIR_BASE.rstrip("/") + "/" + path.lstrip("/")
    resp = requests.get(url, params=params, headers=build_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()

# -----------------------
# NLP -> filter extraction (using spaCy entities + rules)
# -----------------------
def parse_query_spacy(query: str) -> Dict[str, Any]:
    doc = nlp(query)
    q_lower = query.lower()

    filters = {"age_min": None, "age_max": None, "gender": None, "conditions": []}

    # 1) Extract ages from Entities and text
    # Check for explicit patterns added by EntityRuler
    for ent in doc.ents:
        if ent.label_ == "AGE_EXACT":
            # ent.text like "age 45" or "aged 45" -> extract digits
            m = re.search(r"(\d{1,3})", ent.text)
            if m:
                filters["age_min"] = int(m.group(1))
                filters["age_max"] = int(m.group(1))
        elif ent.label_ == "AGE_MIN":
            m = re.search(r"(\d{1,3})", ent.text)
            if m:
                filters["age_min"] = int(m.group(1))
        elif ent.label_ == "AGE_MAX":
            m = re.search(r"(\d{1,3})", ent.text)
            if m:
                filters["age_max"] = int(m.group(1))
        elif ent.label_ == "AGE_RANGE":
            nums = re.findall(r"(\d{1,3})", ent.text)
            if len(nums) >= 2:
                a, b = int(nums[0]), int(nums[1])
                filters["age_min"], filters["age_max"] = min(a, b), max(a, b)
        elif ent.label_ == "GENDER":
            if "female" in ent.text.lower():
                filters["gender"] = "female"
            elif "male" in ent.text.lower():
                filters["gender"] = "male"
        elif ent.label_ == "CONDITION":
            t = ent.text.strip()
            # map to CONDITION_MAP if available, else keep term
            mapped = CONDITION_MAP.get(t.lower())
            if mapped:
                filters["conditions"].append(mapped.copy())
            else:
                filters["conditions"].append({"term": t})

    # 2) fallback: naive scanning for condition names if none found
    if not filters["conditions"]:
        for key, val in CONDITION_MAP.items():
            if re.search(r"\b" + re.escape(key) + r"\b", q_lower):
                filters["conditions"].append(val.copy())

    return filters

# -----------------------
# Map filters -> FHIR search params
# -----------------------
def build_fhir_queries(filters: Dict[str, Any]) -> Dict[str, Any]:
    today = date.today()
    patient_params = {}
    condition_params = {}

    if filters.get("age_min") is not None:
        bd = subtract_years(today, filters["age_min"])
        # birthdate le YYYY-MM-DD (older than or equal to age_min)
        patient_params["birthdate"] = f"le{bd.isoformat()}"
    if filters.get("age_max") is not None:
        bd = subtract_years(today, filters["age_max"])
        # if birthdate already exists we convert to comma-separated ? We'll keep simple:
        existing = patient_params.get("birthdate")
        if existing:
            patient_params["birthdate"] = existing + "," + f"ge{bd.isoformat()}"
        else:
            patient_params["birthdate"] = f"ge{bd.isoformat()}"
    if filters.get("gender"):
        patient_params["gender"] = filters["gender"]

    # condition params: if codes available use code param; else clinical-name (text)
    codes = []
    for cond in filters.get("conditions", []):
        if cond.get("code") and cond.get("system"):
            codes.append(f"{cond['system']}|{cond['code']}")
        elif cond.get("term"):
            # clinical-name is a common custom param; fallback to 'code:text' or use _text
            # We'll use clinical-name to preserve intent; servers may vary.
            condition_params.setdefault("clinical-name", []).append(cond["term"])

    # join params that have multiple values
    if codes:
        # Condition?code=system|code1,system|code2
        condition_params["code"] = ",".join(codes)
    if "clinical-name" in condition_params:
        condition_params["clinical-name"] = ",".join(condition_params["clinical-name"])

    return {"patient": patient_params, "condition": condition_params}

# -----------------------
# Invocation: query FHIR and return aggregated friendly view
# -----------------------
def query_fhir_and_aggregate(filters: Dict[str, Any]) -> Dict[str, Any]:
    queries = build_fhir_queries(filters)
    output = {"fhir_queries": queries, "patient_bundle": None, "condition_bundle": None, "patients": []}

    # Call Patient search if we have patient params or always (optional)
    try:
        patient_bundle = call_fhir("Patient", params=queries["patient"] or None)
        output["patient_bundle"] = patient_bundle
    except requests.HTTPError as e:
        output["patient_error"] = f"Patient search failed: {str(e)}"

    # Call Condition search
    try:
        condition_bundle = call_fhir("Condition", params=queries["condition"] or None)
        output["condition_bundle"] = condition_bundle
    except requests.HTTPError as e:
        output["condition_error"] = f"Condition search failed: {str(e)}"

    # Basic aggregation: map patient id -> name/age/gender and attach condition texts (if available)
    # Servers return 'entry' list with 'resource' objects
    pid_to_patient = {}
    if output.get("patient_bundle") and isinstance(output["patient_bundle"].get("entry"), list):
        for entry in output["patient_bundle"]["entry"]:
            r = entry.get("resource", {})
            pid = r.get("id")
            if not pid:
                continue
            name = ""
            if r.get("name"):
                n0 = r["name"][0]
                given = n0.get("given", [""])[0]
                family = n0.get("family", "")
                name = f"{given} {family}".strip()
            birthDate = r.get("birthDate")
            gender = r.get("gender")
            # simple age calc if birthDate present
            age = None
            if birthDate:
                try:
                    by = int(birthDate.split("-")[0])
                    age = date.today().year - by
                except Exception:
                    age = None
            pid_to_patient[pid] = {"id": pid, "name": name, "birthDate": birthDate, "age": age, "gender": gender, "conditions": []}

    # attach condition resources referencing patient/{id}
    if output.get("condition_bundle") and isinstance(output["condition_bundle"].get("entry"), list):
        for entry in output["condition_bundle"]["entry"]:
            c = entry.get("resource", {})
            subject = c.get("subject", {}).get("reference", "")
            # expected format: "Patient/<id>"
            m = None
            if subject:
                parts = subject.split("/")
                if len(parts) >= 2 and parts[0].lower() == "patient":
                    m = parts[1]
            cond_text = ""
            if c.get("code"):
                if isinstance(c["code"].get("text"), str):
                    cond_text = c["code"].get("text")
                elif isinstance(c["code"].get("coding"), list) and c["code"]["coding"]:
                    cond_text = c["code"]["coding"][0].get("display", "")
            if m and m in pid_to_patient:
                pid_to_patient[m]["conditions"].append(cond_text)
            else:
                # Unattached condition: optionally aggregate separately
                pass

    output["patients"] = list(pid_to_patient.values())
    return output

# -----------------------
# Flask app and route
# -----------------------
app = Flask(__name__)

@app.route("/interpret", methods=["POST"])
def interpret():
    body = request.get_json(force=True)
    query = body.get("query", "")
    if not query:
        return jsonify({"error": "Empty query"}), 400

    filters = parse_query_spacy(query)
    # Build queries (for debugging / UI)
    queries = build_fhir_queries(filters)

    # Call FHIR and aggregate results
    results = query_fhir_and_aggregate(filters)

    return jsonify({"query": query, "filters": filters, "fhir_queries": queries, "results": results})

if __name__ == "__main__":
    # Run development servr
    app.run(host='0.0.0.0', port=8000, debug=True, use_reloader=False)
