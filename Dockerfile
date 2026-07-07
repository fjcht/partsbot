# Actualizamos a la versión 1.44.0 para que coincida con tu entorno
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Instalamos libpq-dev para Postgres
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]