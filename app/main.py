from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from pydantic import BaseModel
from datetime import datetime
import psycopg2
import os
import shutil # Added for file operations

app = FastAPI()

# Directory to store uploaded images
UPLOAD_DIRECTORY = "./uploaded_images"
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

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

@app.post("/api/capturas", status_code=201) # Retorna 201 Created para sucesso
async def registrar_captura(
    placa: str = Form(...),
    status: str = Form(...),
    imagem: UploadFile = File(...) # Imagem é obrigatória
):
    file_location = None
    try:
        # Validação básica do nome do arquivo (pode ser mais robusta)
        original_filename = os.path.basename(imagem.filename)
        if not original_filename:
            raise HTTPException(status_code=400, detail="Nome de arquivo da imagem inválido.")

        timestamp_str = datetime.now().strftime("%Y%m%d%H%M%S%f") # Adicionado %f para maior singularidade
        saved_filename = f"{timestamp_str}_{original_filename}"
        file_location = os.path.join(UPLOAD_DIRECTORY, saved_filename)

        # Salvar o arquivo upado
        try:
            with open(file_location, "wb+") as file_object:
                shutil.copyfileobj(imagem.file, file_object)
        except IOError as io_err:
            raise HTTPException(status_code=500, detail=f"Erro ao salvar a imagem: {io_err}")
        finally:
            await imagem.close() # Sempre fechar o arquivo da imagem

        # Salvar metadados no banco
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO capturas (placa, status, horario, nome_imagem) VALUES (%s, %s, %s, %s)",
                    (placa.upper(), status.upper(), datetime.now(), saved_filename)
                )
                conn.commit()
        
        return {"message": "Captura registrada com sucesso", "filename": saved_filename}

    except HTTPException: # Re-lança HTTPExceptions já tratadas
        raise
    except psycopg2.Error as db_err:
        if file_location and os.path.exists(file_location):
            os.remove(file_location) # Tenta remover arquivo órfão em caso de erro no DB
        raise HTTPException(status_code=503, detail=f"Database error: {db_err}")
    except Exception as e:
        if file_location and os.path.exists(file_location):
            os.remove(file_location) # Tenta remover arquivo órfão
        # É importante fechar o arquivo da imagem mesmo em caso de exceção não prevista
        if imagem and not imagem.file.closed:
             await imagem.close()
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro inesperado: {str(e)}")