FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agentkit ./agentkit
COPY app ./app
COPY frontend ./frontend
EXPOSE 8400
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8400"]
