from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import snowflake.connector
import json
import os
import base64
import tempfile
from typing import Optional

app = FastAPI(title="API Devis Rénovation Cuisine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SNOWFLAKE_CONFIG = {
    "account": os.getenv("SNOWFLAKE_ACCOUNT", "KAWZJSM-GQ93309"),
    "user": os.getenv("SNOWFLAKE_USER", "JOUDZOUZA"),
    "password": os.getenv("SNOWFLAKE_PASSWORD"),
    "warehouse": "COMPUTE_WH",
    "database": "PROJET_IA",
    "schema": "BATIMENTS",
    "role": "ACCOUNTADMIN",
}


class DevisRequest(BaseModel):
    prompt: str = ""
    image_base64: Optional[str] = None
    image_type: Optional[str] = "image/jpeg"


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


def get_catalog_text(cur):
    cur.execute("""
        SELECT DTU_CODE, DESCRIPTION, UNIT, PRICE 
        FROM PROJET_IA.BATIMENTS.V_DTU_CATALOG 
        ORDER BY DTU_CODE
    """)
    catalog = cur.fetchall()
    return "\n".join([
        f"- {r[1]} (code: {r[0]}, unité: {r[2]}, prix: {r[3]}€/{r[2]})"
        for r in catalog
    ])


def build_system_prompt(catalog_text, has_image=False):
    image_rule = ""
    if has_image:
        image_rule = "6. Analyse l'image pour identifier l'état de la cuisine et les travaux nécessaires.\n"

    return f"""Tu es un expert en rénovation de cuisines.
Sélectionne les prestations nécessaires UNIQUEMENT depuis le catalogue ci-dessous.

CATALOGUE DES PRESTATIONS :
{catalog_text}

RÈGLES :
1. Sélectionne UNIQUEMENT des prestations du catalogue.
2. Pour les m², utilise la surface du