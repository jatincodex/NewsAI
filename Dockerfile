FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create directories for generated media
RUN mkdir -p data/generated_videos data/generated_images data/trusted_docs

# Expose default port (Render overrides with $PORT env var)
EXPOSE 8081

# Start command — Render injects $PORT automatically
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8081} --workers 1 --loop asyncio
