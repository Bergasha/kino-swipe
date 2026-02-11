FROM python:3.11-slim

WORKDIR /app


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY app.py .


RUN mkdir -p /app/data /app/static

EXPOSE 5005

CMD ["python", "app.py"]