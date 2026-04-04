# api_devis.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import snowflake.connector
import json
import os

app = FastAPI(title="API Devis Rénovation Cuisine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SNOWFLAKE_CONFIG = {
    "account": os.getenv("SNOWFLAKE_ACCOUNT", "lt50162"),
    "user": os.getenv("SNOWFLAKE_USER", "JOUDZOUZA"),
    "password": os.getenv("SNOWFLAKE_PASSWORD"),
    "warehouse": "COMPUTE_WH",
    "database": "PROJET_IA",
    "schema": "BATIMENTS",
    "role": "ACCOUNTADMIN",
}

class DevisRequest(BaseModel):
    prompt: str

class Prestation(BaseModel):
    dtu_code: str
    description: str
    unite: str
    quantite: float
    prix_unitaire: float
    total: float

class DevisResponse(BaseModel):
    analyse: str
    prestations: list[Prestation]
    total_ht: float
    total_ttc: float

def get_snowflake_connection():
    return snowflake.connector.connect(**SNOWFLAKE_CONFIG)

@app.get("/catalog")
def get_catalog():
    conn = get_snowflake_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DTU_CODE, DESCRIPTION, UNIT, PRICE 
            FROM PROJET_IA.BATIMENTS.V_DTU_CATALOG 
            ORDER BY DTU_CODE
        """)
        rows = cur.fetchall()
        return [
            {"dtu_code": r[0], "description": r[1], "unit": r[2], "price": r[3]}
            for r in rows
        ]
    finally:
        conn.close()

@app.post("/devis", response_model=DevisResponse)
def generer_devis(request: DevisRequest):
    conn = get_snowflake_connection()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT DTU_CODE, DESCRIPTION, UNIT, PRICE 
            FROM PROJET_IA.BATIMENTS.V_DTU_CATALOG 
            ORDER BY DTU_CODE
        """)
        catalog = cur.fetchall()
        catalog_text = "\n".join([
            f"- {r[1]} (code: {r[0]}, unité: {r[2]}, prix: {r[3]}€/{r[2]})"
            for r in catalog
        ])

        system_prompt = f"""Tu es un expert en rénovation de cuisines.
Tu dois analyser la demande du client et sélectionner les prestations nécessaires depuis le catalogue ci-dessous.

CATALOGUE DES PRESTATIONS :
{catalog_text}

RÈGLES :
1. Sélectionne UNIQUEMENT des prestations du catalogue.
2. Pour les m², utilise la surface du client.
3. Pour les ml, estime le périmètre.
4. Pour les forfaits, quantité = 1.
5. Pour les unités, estime le nombre.

Réponds UNIQUEMENT en JSON valide :
{{
  "analyse": "courte analyse",
  "prestations": [
    {{"dtu_code": "DTUXXX", "description": "desc", "unite": "u", "quantite": 0, "prix_unitaire": 0, "total": 0}}
  ],
  "total_general": 0
}}"""

        full_prompt = f"{system_prompt}\n\nDEMANDE DU CLIENT : {request.prompt}"
        escaped = full_prompt.replace("'", "''")

        cur.execute(f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large', '{escaped}') AS RESPONSE
        """)
        response_text = cur.fetchone()[0]

        start = response_text.find('{')
        end = response_text.rfind('}') + 1
        if start < 0 or end <= start:
            raise HTTPException(status_code=500, detail="LLM n'a pas retourné de JSON valide")

        devis = json.loads(response_text[start:end])
        prestations = devis.get("prestations", [])
        total_ht = devis.get("total_general", sum(p.get("total", 0) for p in prestations))

        return DevisResponse(
            analyse=devis.get("analyse", ""),
            prestations=[Prestation(**p) for p in prestations],
            total_ht=total_ht,
            total_ttc=total_ht * 1.2,
        )
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Erreur de parsing JSON du LLM")
    finally:
        conn.close()

@app.get("/health")
def health():
    return {"status": "ok"}