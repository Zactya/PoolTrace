FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home appuser && mkdir /app/data && chown appuser /app/data
USER appuser
ENV POOLTRACE_DATA_DIR=/app/data
EXPOSE 8765
CMD ["sh", "-c", "python -m pooltrace demo && uvicorn pooltrace.api:app --host 0.0.0.0 --port 8765"]
