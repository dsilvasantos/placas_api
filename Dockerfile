FROM python:3.11

WORKDIR /app_code

RUN pip install fastapi psycopg2-binary uvicorn python-multipart jinja2

COPY ./app/ /app_code/

# Copia o diretório 'templates' para dentro de /app_code/templates
COPY ./templates /app_code/templates

EXPOSE 8000

# ATENÇÃO: O comando Uvicorn muda para "main:app"
# porque main.py está agora diretamente no WORKDIR (/app_code),
# e não dentro de um subdiretório 'app'.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]