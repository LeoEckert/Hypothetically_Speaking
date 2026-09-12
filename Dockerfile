FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY scripts/ scripts/

# Bake GenAge/DrugAge CSVs into the image at build time (HAGR has no query API
# — see docs/ARCHITECTURE.md). The tool already degrades to a mock/empty
# result gracefully if these are missing, so a flaky fetch shouldn't fail the
# whole image build.
RUN python scripts/fetch_datasets.py || true

EXPOSE 8000
CMD ["uvicorn", "backend.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
