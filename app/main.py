from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Request, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles # Optional: if you want to serve static files like CSS
from pydantic import BaseModel, Field
import re
from datetime import datetime
import psycopg2
import os
import shutil
from typing import Optional, List, Dict, Any


app = FastAPI()

DB_CONFIG = {
    "dbname": os.getenv("POSTGRES_DB", "placas"),
    "user": os.getenv("POSTGRES_USER", "placa"),
    "password": os.getenv("POSTGRES_PASSWORD", "placa"),
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT", "5432"),
}

UPLOAD_DIRECTORY = "./uploaded_images"
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

templates = Jinja2Templates(directory="templates")



def get_connection():
    return psycopg2.connect(**DB_CONFIG)

class PlacaAutorizadaPayload(BaseModel):
    placa: str = Field(
        ...,
        min_length=7,
        max_length=7, 
        description="Placa do veículo (formato antigo ABC1234 ou Mercosul ABC1D23)."
    )

@app.post("/api/placas_autorizadas", status_code=201)
async def cadastrar_placa_autorizada(payload: PlacaAutorizadaPayload):
    """
    Registra uma nova placa de veículo como autorizada.
    A placa deve seguir o formato brasileiro antigo (LLLNNNN) ou Mercosul (LLLNLNN).
    """

    normalized_placa = payload.placa.strip().upper()

    placa_regex = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$|^[A-Z]{3}[0-9]{4}$")
    if not placa_regex.match(normalized_placa):
        raise HTTPException(
            status_code=422, # Unprocessable Entity for validation errors
            detail="Formato da placa inválido. Use o formato ABC1234 ou ABC1D23."
        )

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO placas_autorizadas (placa) VALUES (%s) RETURNING id",
                    (normalized_placa,)
                )
                result = cur.fetchone()
                if result is None:
                    conn.rollback() 
                    raise HTTPException(status_code=500, detail="Falha ao registrar a placa e obter o ID.")
                
                novo_id = result[0]
                conn.commit()
        return {
            "message": "Placa autorizada cadastrada com sucesso!",
            "id": novo_id,
            "placa": normalized_placa
        }
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(
            status_code=409, # Conflict
            detail=f"A placa '{normalized_placa}' já está cadastrada."
        )
    except psycopg2.Error as db_err:
        raise HTTPException(status_code=503, detail=f"Erro de banco de dados: {db_err}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro inesperado: {str(e)}")

@app.get("/api/placas/{placa}")
def verificar_placa(placa: str):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT EXISTS(SELECT 1 FROM placas_autorizadas WHERE placa = %s)", (placa.upper(),)) #
                existe = cur.fetchone()[0]
        return {"liberado": existe}
    except psycopg2.Error as db_err:
        raise HTTPException(status_code=503, detail=f"Database error: {db_err}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/capturas", status_code=201)
async def registrar_captura(
    placa: str = Form(...),
    status: str = Form(...),
    imagem: UploadFile = File(...)
):
    file_location = None
    original_filename = None
    if imagem and imagem.filename:
        original_filename = os.path.basename(imagem.filename)

    if not original_filename: 
        raise HTTPException(status_code=400, detail="Nome de arquivo da imagem inválido.")

    try:
        timestamp_str = datetime.now().strftime("%Y%m%d%H%M%S%f")
        saved_filename = f"{timestamp_str}_{original_filename}"
        file_location = os.path.join(UPLOAD_DIRECTORY, saved_filename)

        try:
            with open(file_location, "wb+") as file_object:
                shutil.copyfileobj(imagem.file, file_object)
        except IOError as io_err:
            raise HTTPException(status_code=500, detail=f"Erro ao salvar a imagem: {io_err}")
        finally:
            await imagem.close()

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO capturas (placa, status, horario, nome_imagem) VALUES (%s, %s, %s, %s)", #
                    (placa.upper(), status.upper(), datetime.now(), saved_filename)
                )
                conn.commit()
        
        return {"message": "Captura registrada com sucesso", "filename": saved_filename}

    except HTTPException:
        raise
    except psycopg2.Error as db_err:
        if file_location and os.path.exists(file_location):
            os.remove(file_location)
        raise HTTPException(status_code=503, detail=f"Database error: {db_err}")
    except Exception as e:
        if file_location and os.path.exists(file_location):
            os.remove(file_location)
        if imagem and hasattr(imagem, 'file') and not imagem.file.closed:
             await imagem.close()
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro inesperado: {str(e)}")


# --- NEW: Web Page Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    # Simple root page that links to the new web interfaces
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/web/consulta-placa", response_class=HTMLResponse)
async def web_consulta_placa_page(request: Request):
    return templates.TemplateResponse("consulta_placa.html", {"request": request})

@app.get("/web/ultimas-capturas", response_class=HTMLResponse)
async def web_ultimas_capturas_page(request: Request):
    return templates.TemplateResponse("ultimas_capturas.html", {"request": request})

@app.get("/web/cadastro-veiculo", response_class=HTMLResponse)
async def web_cadastro_veiculo_page(request: Request):
    return templates.TemplateResponse("cadastro_veiculo.html", {"request": request})

# --- NEW: API Endpoints for Web Pages ---

def format_captura_row(row: tuple) -> Dict[str, Any]:
    return {
        "id": row[0],
        "placa": row[1],
        "status": row[2],
        "horario": row[3].isoformat() if isinstance(row[3], datetime) else row[3],
        "nome_imagem": row[4]
    }

@app.get("/api/capturas/filtradas", response_model=List[Dict[str, Any]])
async def get_capturas_filtradas(
    placa: Optional[str] = Query(None, min_length=1, max_length=10),
    data_inicio: Optional[datetime] = Query(None),
    data_fim: Optional[datetime] = Query(None),
    status: Optional[str] = Query(None)
):


    base_query = "SELECT id, placa, status, horario, nome_imagem FROM capturas" #
    conditions = []
    params = []

    if placa:
        conditions.append("placa ILIKE %s") 
        params.append(f"%{placa.upper()}%")
    if status:
        conditions.append("status = %s")
        params.append(status.upper())
    if data_inicio:
        conditions.append("horario >= %s")
        params.append(data_inicio)
    if data_fim:
        conditions.append("horario <= %s")
        params.append(data_fim)

    query = base_query
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY horario DESC LIMIT 100" # Add a sensible limit

    capturas_list = []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                resultados = cur.fetchall()
                for row in resultados:
                    capturas_list.append(format_captura_row(row))
        return capturas_list
    except psycopg2.Error as db_err:
        raise HTTPException(status_code=503, detail=f"Database error: {db_err}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/capturas/ultimas", response_model=List[Dict[str, Any]])
async def get_ultimas_capturas():
    capturas_list = []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, placa, status, horario, nome_imagem FROM capturas ORDER BY horario DESC LIMIT 10") #
                resultados = cur.fetchall()
                for row in resultados:
                    capturas_list.append(format_captura_row(row))
        return capturas_list
    except psycopg2.Error as db_err:
        raise HTTPException(status_code=503, detail=f"Database error: {db_err}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if os.path.exists(UPLOAD_DIRECTORY):
    app.mount("/capturas-imagens", StaticFiles(directory=UPLOAD_DIRECTORY), name="capturas-imagens")