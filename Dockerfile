FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY run.py .
COPY app/ ./app/
RUN mkdir -p /app/data
COPY data/sw.js ./data/sw.js
EXPOSE 5005
CMD ["python", "run.py"]
