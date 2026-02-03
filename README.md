# Open Atlas - Munich City Data Explorer
![[Poster.pdf]]
A full-stack web application for exploring Munich's open data with district-level analysis, composite indices, and an AI-powered chatbot.

## Features

- **District-Level Analysis**: Explore data aggregated by Munich's 25 districts with choropleth visualization
- **Composite Indices**: Pre-built indices (Child-Friendly, Senior-Friendly, Public Services) that combine multiple datasets to score districts
- **Custom Index Builder**: Create your own composite indices by combining datasets with custom weights
- **AI Chatbot**: Natural language interface powered by OpenAI to query and analyze Munich data
- **Interactive Map**: Choropleth maps showing district scores with click-to-explore functionality
- **Unified Search**: Search across 100+ datasets from a single interface
- **Real-time Data Sync**: Automatic synchronization with Munich Open Data portal

## Tech Stack

### Backend (Flask)
- Python 3.12+
- Flask with Flask-CORS
- SQLite database with spatial data support
- ChromaDB for vector search (chatbot)
- OpenAI API (embeddings and LLM)

### Frontend (React)
- React 18
- Leaflet & React-Leaflet (Maps)
- Axios (HTTP client)

## Project Structure

```
open-atlas/
├── backend/
│   ├── app.py                 # Flask application (all API endpoints)
│   ├── requirements.txt       # Python dependencies
│   ├── chat/                  # AI chatbot module
│   │   ├── agent.py           # Chat agent with tools
│   │   ├── tools.py           # Agent tools (search, query, etc.)
│   │   └── vector_store.py    # ChromaDB for semantic search
│   └── data/                  # Data layer
│       ├── database.py        # SQLite database operations
│       ├── districts.py       # District boundary service
│       ├── indices.py         # Composite index calculator
│       ├── models.py          # Data models
│       ├── parsers.py         # Data format parsers
│       ├── sync.py            # Data synchronization
│       └── openatlas.db.gz    # Pre-built database (compressed)
├── frontend/
│   ├── src/
│   │   ├── App.js             # Main application
│   │   ├── index.js           # React entry point
│   │   └── components/
│   │       ├── MapView.js     # Interactive map with choropleth
│   │       ├── Chatbot.js     # AI chat interface
│   │       └── Tooltip.js     # UI tooltips
│   └── package.json
├── doc/                       # Development scripts & analysis
│   ├-─ analysis.py            # Database statistics generator
│   └── chaos_map.py           # Data visualization generator
├── start.sh                   # Quick start script
└── README.md
```

## Installation

### Prerequisites
- Python 3.12+
- Node.js 16+
- OpenAI API key (for chatbot)

### Backend Setup

```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Extract the pre-built database
gunzip -k data/openatlas.db.gz

# Set OpenAI API key (for chatbot)
export OPENAI_API_KEY=sk-...

# Start the server
python app.py
```

The API will be available at `http://localhost:5001`

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm start
```

The frontend will open at `http://localhost:3000`

### Quick Start

```bash
./start.sh
```

## API Endpoints

### Districts
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/districts` | GET | Get all districts as GeoJSON |
| `/api/districts/<id>` | GET | Get specific district |
| `/api/districts/<id>/datasets` | GET | Get datasets in district |
| `/api/districts/stats` | GET | Get district statistics |
| `/api/districts/aggregate` | GET | Aggregate dataset by district |

### Datasets
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/datasets` | GET | List datasets (filterable) |
| `/api/v2/datasets/search` | GET | Semantic search datasets |
| `/api/v2/datasets/<id>` | GET | Get dataset details |
| `/api/v2/datasets/<id>/features` | GET | Get features as GeoJSON |
| `/api/v2/stats` | GET | Database statistics |

### Spatial Queries
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/features/near` | GET | Features near a point |
| `/api/v2/features/in-district/<id>` | GET | Features in a district |

### Composite Indices
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/indices/presets` | GET | List available index presets |
| `/api/indices/presets/<id>` | GET | Get preset details |
| `/api/indices/calculate/<id>` | GET | Calculate a preset index |
| `/api/indices/calculate` | POST | Calculate a custom index |
| `/api/indices/datasets` | GET | Datasets available for indices |
| `/api/indices/datasets/<id>/columns` | GET | Get dataset columns |

### Sync
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sync/status` | GET | Get sync status |
| `/api/sync/districts` | POST | Sync district boundaries |
| `/api/sync/start` | POST | Start full data sync |

### Chat
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Send query to AI agent |
| `/api/chat/sync-vectors` | POST | Sync vector store |

### Other
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/sources` | GET | List data sources |

## Composite Indices

The application includes pre-built composite indices that score each district:

- **Child-Friendly**: Playgrounds, schools, childcare, traffic calming, safety metrics
- **Senior-Friendly**: Senior centers, doctor/pharmacy density, care facilities
- **Greenness**: Green spaces, bike lanes, cycling infrastructure
- **Entertainment**: Cultural facilities, swimming pools, tourist POIs, markets
- **Public Services**: WiFi, toilets, recycling, community centers, social services

Each index combines multiple datasets with configurable weights and normalization (per capita, per area, etc.).

## Data Synchronization

To sync fresh data from Munich Open Data portal:

```bash
cd backend
python -c "from data.sync import DataSync; DataSync().full_sync()"
```

This will:
1. Fetch all dataset metadata from CKAN API
2. Download and parse geospatial data (WFS, GeoJSON, CSV)
3. Assign features to districts based on geometry
4. Update the SQLite database

## Development

- Flask runs in debug mode with auto-reload
- React dev server has hot-reload enabled
- Database is stored in `backend/data/openatlas.db`
- Vector store is in `backend/data/.chroma`

## Data Sources

- **Munich Open Data Portal**: https://opendata.muenchen.de
- **CKAN API**: https://opendata.muenchen.de/api/3/action
- **Supported formats**: WFS, GeoJSON, CSV, JSON

## Attribution

This application uses open data provided by:

**Landeshauptstadt München – opendata.muenchen.de**

Licensed under [Datenlizenz Deutschland – Namensnennung – Version 2.0](https://www.govdata.de/dl-de/by-2-0)

## License

This project is for educational purposes.
