# Open Atlas - Munich City Data Explorer

![Poster](doc/poster.png)

A full-stack web application for exploring Munich's open data with district-level analysis, composite indices, and an AI-powered chatbot.

## Features

- **District-Level Analysis** - Explore data aggregated by Munich's 25 districts with choropleth visualization
- **Composite Indices** - Pre-built indices (Child-Friendly, Senior-Friendly, Public Services) scoring districts
- **Custom Index Builder** - Create your own indices by combining datasets with custom weights
- **AI Chatbot** - Natural language interface powered by OpenAI to query Munich data
- **Real-time Data Sync** - Automatic synchronization with Munich Open Data portal

## Tech Stack

**Backend:** Python 3.12+, Flask, SQLite, ChromaDB, OpenAI API
**Frontend:** React 18, Leaflet, Axios

## Quick Start

```bash
./start.sh
```

### Manual Setup

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
gunzip -k data/openatlas.db.gz
export OPENAI_API_KEY=sk-...
python app.py  # API at http://localhost:5001

# Frontend
cd frontend
npm install && npm start  # Opens http://localhost:3000
```

## API Overview

| Category  | Endpoints                                                                                                                                                                                |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Districts | `GET /api/districts`, `/api/districts/<id>`, `/api/districts/<id>/datasets`, `/api/districts/stats`, `/api/districts/aggregate`                                                          |
| Datasets  | `GET /api/v2/datasets`, `/api/v2/datasets/search`, `/api/v2/datasets/<id>`, `/api/v2/datasets/<id>/features`, `/api/v2/stats`                                                            |
| Spatial   | `GET /api/v2/features/near`, `/api/v2/features/in-district/<id>`                                                                                                                         |
| Indices   | `GET /api/indices/presets`, `/api/indices/presets/<id>`, `/api/indices/calculate/<id>`, `POST /api/indices/calculate`, `GET /api/indices/datasets`, `/api/indices/datasets/<id>/columns` |
| Sync      | `GET /api/sync/status`, `POST /api/sync/districts`, `/api/sync/start`                                                                                                                    |
| Chat      | `POST /api/chat`, `/api/chat/sync-vectors`                                                                                                                                               |

## Composite Indices

Pre-built indices that score each district:

- **Child-Friendly** - Playgrounds, schools, childcare, traffic calming
- **Senior-Friendly** - Senior centers, doctor/pharmacy density, care facilities
- **Greenness** - Green spaces, bike lanes, cycling infrastructure
- **Entertainment** - Cultural facilities, pools, tourist POIs, markets
- **Public Services** - WiFi, toilets, recycling, community centers

## Data Sync

```bash
cd backend
python -c "from data.sync import DataSync; DataSync().full_sync()"
```

## Attribution

Data provided by **Landeshauptstadt München** – [opendata.muenchen.de](https://opendata.muenchen.de)
Licensed under [Datenlizenz Deutschland – Namensnennung – Version 2.0](https://www.govdata.de/dl-de/by-2-0)
