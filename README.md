# FHIR NLP Project (Flask backend + Next.js frontend)

## Start backend
cd backend || 
python -m venv venv || 
venv/Scripts/Activate.ps1 || 
pip install -r requirements.txt || 
python -m spacy download en_core_web_sm || 
python fhir_nlp_service.py 

## Start frontend
cd frontend || 
npm install || 
npm run dev || 

Open http://localhost:3000 and use the UI to send natural-language queries.

