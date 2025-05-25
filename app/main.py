from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Request, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles # Optional: if you want to serve static files like CSS

from datetime import datetime
import psycopg2
import os
import shutil
from typing import Optional, List, Dict, Any

# --- Existing App Setup ---
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

# --- NEW: Template Engine Setup ---
templates = Jinja2Templates(directory="templates")

# --- Optional: Mount static files (e.g., for CSS, JS) ---
# If you create a 'static' directory for CSS, uncomment the next line
# app.mount("/static", StaticFiles(directory="static"), name="static")
# And ensure 'static' directory is in your Docker image.

# --- Existing get_connection function ---
def get_connection():
    return psycopg2.connect(**DB_CONFIG)

# --- Existing Endpoints: /api/placas/{placa} and /api/capturas (POST) ---
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

    if not original_filename: # Check if filename is valid after os.path.basename
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
    # Basic validation: at least one filter should ideally be provided for broad queries,
    # but for simplicity, we allow fetching all if no filters are given (could be many results).
    # Consider adding mandatory filters or pagination for production.

    base_query = "SELECT id, placa, status, horario, nome_imagem FROM capturas" #
    conditions = []
    params = []

    if placa:
        conditions.append("placa ILIKE %s") # Using ILIKE for case-insensitive search
        params.append(f"%{placa.upper()}%")
    if status:
        conditions.append("status = %s")
        params.append(status.upper())
    if data_inicio:
        conditions.append("horario >= %s")
        params.append(data_inicio)
    if data_fim:
        # To include the whole end day, typically the frontend sends YYYY-MM-DD,
        # which becomes YYYY-MM-DD 00:00:00. So to include the whole day,
        # you might need to adjust it to YYYY-MM-DD 23:59:59.999999 or add 1 day and use '<'.
        # For simplicity with datetime from Query, exact comparison for now.
        # Or, if data_fim is just a date, you can do: "horario < %s" with data_fim + 1 day.
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

# --- Optional: Endpoint to serve uploaded images ---
# This allows displaying images in the web UI.
# Ensure UPLOAD_DIRECTORY is correctly mapped if using Docker volumes for persistence.
# For security, consider validating filenames and ensuring only intended files are served.
if os.path.exists(UPLOAD_DIRECTORY):
    app.mount("/capturas-imagens", StaticFiles(directory=UPLOAD_DIRECTORY), name="capturas-imagens")