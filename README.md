# Open Atlas - Munich City Data Explorer

A full-stack web application that aggregates and searches across Munich city datasets, featuring an AI-powered chatbot that can query and analyze data from the Munich Open Data portal.

## Features

- **Unified Search**: Search across all datasets from a single interface
- **Category Filtering**: Filter results by data category
- **Dual View Modes**:
  - List view for detailed information
  - Map view for geographic visualization
- **AI Chatbot**: Natural language interface to query Munich Open Data
  - Semantic search across the entire Munich Open Data catalog
  - Automatic dataset selection and analysis
  - Supports CSV and geospatial data analysis
- **Real-time Statistics**: View data counts and search results
- **Responsive Design**: Works on desktop and mobile devices

## Tech Stack

### Main Backend (Flask)
- Python 3.12+
- Flask (REST API)
- Flask-CORS

### Chatbot Backend (FastAPI)
- FastAPI + Uvicorn
- LangChain / LangGraph (AI agent orchestration)
- ChromaDB (vector store for semantic search)
- OpenAI API (embeddings and LLM)
- DuckDB (data analysis with spatial extension)
- Pandas / GeoPandas (data processing)

### Frontend
- React 18
- Axios (HTTP client)
- Leaflet & React-Leaflet (Maps)
- CSS3

## Installation

### Prerequisites
- Python 3.12 or higher
- Node.js 16 or higher
- npm or yarn
- OpenAI API key (for chatbot functionality)

### Main Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Create a virtual environment (recommended):
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Start the Flask server:
```bash
python app.py
```

The backend API will be available at `http://localhost:5001`

### Chatbot Backend Setup

1. Navigate to the chatbot-backend directory:
```bash
cd backend/chatbot-backend
```

2. Create a virtual environment (recommended):
```bash
python -m venv .venv
source .venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set your OpenAI API key by creating a `.env` file:
```bash
OPENAI_API_KEY=sk-...
```

5. Run catalog ingestion to populate the vector store:
```bash
python -m src.ingestion
```

6. Start the FastAPI server:
```bash
python api.py
```

The chatbot API will be available at `http://localhost:8000`

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Start the development server:
```bash
npm start
```

The frontend will automatically open in your browser at `http://localhost:3000`

### Quick Start

Use the included start script to launch the main backend and frontend together:
```bash
./start.sh
```

Note: The chatbot backend needs to be started separately.

## Usage

1. **Start all servers**: Make sure the main backend (Flask), chatbot backend (FastAPI), and frontend (React) servers are running
2. **Search**: Enter keywords in the search bar (e.g., "Markt", "Schwabing", "Parkplatz")
3. **Filter**: Click on category buttons to filter by data type
4. **Toggle Views**: Switch between List and Map view to see results differently
5. **Chat**: Click the chat button to ask natural language questions about Munich data
6. **Explore**: Click on map markers or read list details to learn more

## API Endpoints

### Main Backend (Port 5001)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/search` | GET | Search across all datasets (`q`, `category` params) |
| `/api/categories` | GET | Get all available categories with counts |
| `/api/stats` | GET | Get statistics about the data |
| `/api/health` | GET | Health check endpoint |

### Chatbot Backend (Port 8000)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API information |
| `/health` | GET | Health check endpoint |
| `/query` | POST | Submit a natural language query |
| `/docs` | GET | Swagger UI documentation |

Example chatbot query:
```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "How many bike parking spots are in Schwabing?"}'
```

## Project Structure

```
open-atlas/
├── backend/
│   ├── app.py                    # Flask application
│   ├── requirements.txt          # Python dependencies
│   ├── venv/                     # Virtual environment
│   └── chatbot-backend/
│       ├── api.py                # FastAPI application
│       ├── requirements.txt      # Chatbot dependencies
│       ├── .chroma/              # ChromaDB vector store
│       └── src/
│           ├── agent.py          # LangGraph agent
│           ├── ingestion.py      # Catalog ingestion
│           └── vector_store.py   # ChromaDB operations
├── frontend/
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── components/
│   │   │   ├── SearchBar.js
│   │   │   ├── CategoryFilter.js
│   │   │   ├── ResultsList.js
│   │   │   ├── MapView.js
│   │   │   ├── Stats.js
│   │   │   └── Chatbot.js
│   │   ├── App.js
│   │   ├── App.css
│   │   ├── index.js
│   │   └── index.css
│   └── package.json
├── resources/                    # Resource files
├── start.sh                      # Quick start script
└── README.md
```

## Data Sources

The application accesses data from the Munich Open Data portal:
- **CKAN API**: `https://opendata.muenchen.de/api/3/action`
- **Supported formats**: CSV, WFS, GeoJSON, JSON

The chatbot ingestion process indexes all available datasets for semantic search.

## Development

### Main Backend Development
- The Flask server runs in debug mode by default
- Changes to Python files will automatically reload the server
- API is accessible at `http://localhost:5001/api`

### Chatbot Backend Development
- FastAPI auto-reloads on file changes when run with uvicorn
- API documentation available at `http://localhost:8000/docs`
- Vector store is persisted in `.chroma` directory

### Frontend Development
- React development server has hot-reload enabled
- Changes to React components will update instantly

## Troubleshooting

### CORS Issues
- Flask-CORS and FastAPI CORS middleware are configured to allow all origins in development
- For production, update the allowed origins lists

### Chatbot Not Responding
- Verify the OpenAI API key is set correctly in `.env`
- Run the ingestion script to populate the vector store
- Check the FastAPI server logs for errors

### Map Not Displaying
- Check that Leaflet CSS is loaded in index.html
- Verify coordinates are in the correct format

### Data Not Loading
- Verify all JSON files are in the correct directory
- Check the backend console for file loading errors

## License

This project is for educational purposes.
