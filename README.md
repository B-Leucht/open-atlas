# Munich City Data Search

A full-stack web application that aggregates and searches across multiple Munich city datasets including markets, bike infrastructure, city districts, Isar danger zones, disabled parking, and more.

## Features

- **Unified Search**: Search across all datasets from a single interface
- **Category Filtering**: Filter results by data category
- **Dual View Modes**:
  - List view for detailed information
  - Map view for geographic visualization
- **Real-time Statistics**: View data counts and search results
- **Responsive Design**: Works on desktop and mobile devices

## Data Sources

The application aggregates data from:
- Markets (märkte.json) - 54 locations
- Bike Infrastructure (Radlstadtplan.json)
- City Districts (stadtviertel.json)
- Isar Danger Zones (isar-gefahrenstellen.json)
- Disabled Parking (behindertenparkplätze.json)
- Features (features.json)

## Tech Stack

### Backend
- Python 3.8+
- Flask (REST API)
- Flask-CORS

### Frontend
- React 18
- Axios (HTTP client)
- Leaflet & React-Leaflet (Maps)
- CSS3

## Installation

### Prerequisites
- Python 3.8 or higher
- Node.js 16 or higher
- npm or yarn

### Backend Setup

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

The backend API will be available at `http://localhost:5000`

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

## Usage

1. **Start both servers**: Make sure both the backend (Flask) and frontend (React) servers are running
2. **Search**: Enter keywords in the search bar (e.g., "Markt", "Schwabing", "Parkplatz")
3. **Filter**: Click on category buttons to filter by data type
4. **Toggle Views**: Switch between List and Map view to see results differently
5. **Explore**: Click on map markers or read list details to learn more

## API Endpoints

### GET /api/search
Search across all datasets
- Query params: `q` (search query), `category` (filter by category)
- Returns: JSON with search results

### GET /api/categories
Get all available categories
- Returns: List of categories with counts

### GET /api/stats
Get statistics about the data
- Returns: Total features, category breakdown

### GET /api/health
Health check endpoint
- Returns: Server status

## Project Structure

```
code/
├── backend/
│   ├── app.py              # Flask application
│   └── requirements.txt    # Python dependencies
├── frontend/
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── components/
│   │   │   ├── SearchBar.js
│   │   │   ├── CategoryFilter.js
│   │   │   ├── ResultsList.js
│   │   │   ├── MapView.js
│   │   │   └── Stats.js
│   │   ├── App.js
│   │   ├── App.css
│   │   ├── index.js
│   │   └── index.css
│   └── package.json
├── *.json                  # Data files
└── README.md
```

## Development

### Backend Development
- The Flask server runs in debug mode by default
- Changes to Python files will automatically reload the server
- API is accessible at `http://localhost:5000/api`

### Frontend Development
- React development server has hot-reload enabled
- Changes to React components will update instantly
- Proxy is configured to forward API requests to the backend

## Troubleshooting

### CORS Issues
If you see CORS errors, make sure:
- Flask-CORS is installed in the backend
- Both servers are running on their default ports

### Map Not Displaying
- Check that Leaflet CSS is loaded in index.html
- Verify coordinates are in the correct format
- Some coordinates may need projection conversion

### Data Not Loading
- Verify all JSON files are in the correct directory
- Check the backend console for file loading errors
- Ensure file paths in app.py are correct

## Future Enhancements

- [ ] Add advanced filtering (date ranges, distance)
- [ ] Implement proper coordinate projection (proj4js)
- [ ] Add result sorting options
- [ ] Export search results (CSV, JSON)
- [ ] Add favorites/bookmarks
- [ ] Implement pagination for large result sets
- [ ] Add clustering for map markers
- [ ] Support for polygon/line geometries on map

## License

This project is for educational purposes.

## Contact

For questions or issues, please contact the project maintainer.
