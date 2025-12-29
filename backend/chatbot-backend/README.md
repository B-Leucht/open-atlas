## Munich Open Data Chatbot

This project implements a local, agentic RAG chatbot for the Munich Open Data portal, following the specification in `SPECIFICATIONS.md`.

### Quick Start

1. **Create and activate a virtual environment** (optional but recommended):

```bash
cd path/to/your/clone/backend/chatbot-backend
python -m venv .venv
source .venv/bin/activate  # on macOS/Linux
```

2. **Install dependencies**:

```bash
pip install -r requirements.txt
```

3. **Set your OpenAI API key**:

- Create a `.env` file in the project root with:

```bash
OPENAI_API_KEY=sk-...
```

4. **Run catalog ingestion (Smart Catalog)**:

This step calls the CKAN JSON API, filters for usable formats, and stores metadata in a local ChromaDB collection named `munich_data_catalog`.

```bash
python -m src.ingestion
```

You can optionally limit the number of packages ingested for testing by editing `ingestion.py` and calling:

```python
ingest_catalog(max_packages=200)
```

5. **Launch the application**:

**Option A: FastAPI API (Recommended for programmatic access)**

```bash
python api.py
```

Or using uvicorn directly:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. You can:
- View API documentation at `http://localhost:8000/docs` (Swagger UI)
- Query the agent via POST requests to `http://localhost:8000/query`

Example query:

```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "How many bike parking spots are in Schwabing?"}'
```

**Option B: Streamlit UI (For interactive web interface)**

```bash
streamlit run app.py
```

Then open the provided local URL in your browser.

### Manual Setup / Notes

- **Network access**: Both ingestion and the agent at runtime access:
  - The Munich CKAN API (`https://opendata.muenchen.de/api/3/action/...`)
  - Remote dataset URLs (CSV, WFS, GeoJSON, JSON)
  - The OpenAI API (for `langchain-openai` / `ChatOpenAI`)
- **DuckDB spatial extension**:
  - The geospatial tool uses `duckdb.install_extension('spatial')` and `duckdb.load_extension('spatial')`. DuckDB will download the extension on first use; make sure your environment allows this.
- **ChromaDB persistence**:
  - By default, embeddings and catalog metadata are stored in a local `.chroma` directory.
- **Non-hallucination behavior**:
  - If a dataset link is broken or a query cannot be executed, the agent returns an explicit, user-facing error message instead of fabricating results.


