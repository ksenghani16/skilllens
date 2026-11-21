FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY skilllens ./skilllens
COPY benchmarks ./benchmarks
COPY config.yaml .
# run as a non-root user
RUN useradd -m app && mkdir -p /app/runs /app/.cache && chown -R app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "skilllens.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
