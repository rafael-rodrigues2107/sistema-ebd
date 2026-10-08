FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código
COPY . .

# Pasta de dados (uploads; banco SQLite em instalações antigas)
RUN mkdir -p /data

# Ajusta diretório de trabalho para a pasta do pacote Python
WORKDIR /app/app

EXPOSE 8000

CMD ["sh", "/app/entrypoint.sh"]
