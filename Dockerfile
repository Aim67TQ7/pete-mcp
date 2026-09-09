FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gateway/ gateway/
COPY migrations/ migrations/

EXPOSE 8080
# Server by default; worker container overrides CMD (see docker-compose.yml).
CMD ["python", "-m", "gateway.server"]
