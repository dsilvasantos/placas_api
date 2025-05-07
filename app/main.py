from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
import psycopg2
import os

app = FastAPI()

DB_CONFIG = {
    "dbname": os.getenv("POSTGRES_DB", "placas"),
    "user": os.getenv("POSTGRES_USER", "placa"),
    "password": os.getenv("POSTGRES_PASSWORD", "placa"),
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT", "5432"),
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

class Captura(BaseModel):
    placa: str
    status: str

@app.get("/api/placas/{placa}")
def verificar_placa(placa: str):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT EXISTS(SELECT 1 FROM placas_autorizadas WHERE placa = %s)", (placa.upper(),))
        existe = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {"liberado": existe}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/capturas")
def registrar_captura(captura: Captura):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO capturas (placa, status, horario) VALUES (%s, %s, %s)",
                    (captura.placa.upper(), captura.status.upper(), datetime.now()))
        conn.commit()
        cur.close()
        conn.close()
        return {"message": "Captura registrada com sucesso"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))