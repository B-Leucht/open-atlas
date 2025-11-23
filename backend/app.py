from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from typing import List, Dict, Any
from functools import lru_cache

app = Flask(__name__)
CORS(app)

# Get the absolute path to the data directory (one level up from backend)
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)))

@lru_cache(maxsize=None)
def load_json_file(filename: str) -> Dict[str, Any]:
    """Load and cache JSON files"""
    filepath = os.path.join(DATA_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return {"type": "FeatureCollection", "features": []}

def search_features(features: List[Dict], query: str) -> List[Dict]:
    """Search through features based on query string"""
    # If no query, return all features
    if not query or query.strip() == '':
        return features

    query_lower = query.lower().strip()
    results = []

    for feature in features:
        # Search in all properties
        properties = feature.get('properties', {})

        # Convert all property values to string and search
        searchable_text = ' '.join(
            str(v).lower() for v in properties.values() if v is not None
        )

        if query_lower in searchable_text:
            results.append(feature)

    return results

def aggregate_data() -> List[Dict]:
    """Aggregate all data sources into a unified format"""
    data_files = {
        'markets': 'märkte.json',
        'bike_infrastructure': 'Radlstadtplan.json',
        'districts': 'stadtviertel.json',
        'isar_dangers': 'isar-gefahrenstellen.json',
        'disabled_parking': 'behindertenparkplätze.json',
        'waste_disposal': 'Abfallentsorgungsanlagen.json',
        'accessible_glass_containers': 'BarrierefreieAltglasContainer.json',
        'charging_infrastructure': 'Ladeinfrastruktur.json',
        'community_centers': 'Nachbarschaftstreffs.json',
        'bike_service_stations': 'Radlservicestationen.json',
        'environmental_zone': 'umweltzone.json',
        'recycling_islands': 'wertstoffinseln.json'
    }

    aggregated = []

    for category, filename in data_files.items():
        data = load_json_file(filename)
        features = data.get('features', [])

        # Add category to each feature
        for feature in features:
            feature['category'] = category
            aggregated.append(feature)

    return aggregated

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km using Haversine formula"""
    from math import radians, sin, cos, sqrt, atan2

    R = 6371  # Earth's radius in km

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    return R * c

def convert_utm_to_latlon(x, y):
    """Convert UTM Zone 32N (EPSG:25832) to lat/lon (EPSG:4326)"""
    try:
        # Rough approximation for Munich area
        # For production, use pyproj library
        from math import pi

        # UTM Zone 32N parameters
        k0 = 0.9996
        false_easting = 500000
        false_northing = 0

        # Remove false easting
        x = x - false_easting

        # Rough conversion (simplified)
        lon = 11.5 + (x / 111320)  # Munich longitude base
        lat = y / 111320 - 1000     # Adjust for northing

        return lat, lon
    except:
        return None, None

@app.route('/api/search', methods=['GET'])
def search():
    """Search endpoint for all data"""
    query = request.args.get('q', '')
    categories_param = request.args.get('categories', '')
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)

    print(f"Search request - Query: '{query}', Categories: '{categories_param}', Lat: {lat}, Lon: {lon}")

    # Get all aggregated data
    all_data = aggregate_data()
    print(f"Total features loaded: {len(all_data)}")

    # Filter by categories if specified
    if categories_param and categories_param != 'all':
        selected_categories = [c.strip() for c in categories_param.split(',')]
        all_data = [f for f in all_data if f.get('category') in selected_categories]
        print(f"After category filter ({', '.join(selected_categories)}): {len(all_data)}")

    # Search through features
    results = search_features(all_data, query)
    print(f"Search results: {len(results)}")

    # Add distance and sort by proximity if location provided
    if lat and lon:
        for feature in results:
            if feature.get('geometry') and feature['geometry'].get('type') == 'Point':
                coords = feature['geometry']['coordinates']

                # Convert coordinates if needed
                if coords[0] > 180:  # UTM coordinates
                    feature_lat, feature_lon = convert_utm_to_latlon(coords[0], coords[1])
                else:
                    feature_lon, feature_lat = coords

                if feature_lat and feature_lon:
                    distance = calculate_distance(lat, lon, feature_lat, feature_lon)
                    feature['distance_km'] = round(distance, 2)

        # Sort by distance
        results = sorted(results, key=lambda x: x.get('distance_km', float('inf')))

    return jsonify({
        'query': query,
        'categories': categories_param,
        'count': len(results),
        'results': results  # Return all results
    })

@app.route('/api/categories', methods=['GET'])
def categories():
    """Get all available categories with counts"""
    all_data = aggregate_data()

    category_counts = {}
    for feature in all_data:
        cat = feature.get('category', 'unknown')
        category_counts[cat] = category_counts.get(cat, 0) + 1

    return jsonify({
        'categories': [
            {'id': cat, 'name': cat.replace('_', ' ').title(), 'count': count}
            for cat, count in category_counts.items()
        ],
        'total': len(all_data)
    })

@app.route('/api/stats', methods=['GET'])
def stats():
    """Get statistics about the data"""
    all_data = aggregate_data()

    category_counts = {}
    for feature in all_data:
        cat = feature.get('category', 'unknown')
        category_counts[cat] = category_counts.get(cat, 0) + 1

    return jsonify({
        'total_features': len(all_data),
        'categories': category_counts,
        'data_sources': len(category_counts)
    })

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

@app.route('/')
def index():
    """Root endpoint with API documentation"""
    return jsonify({
        'message': 'Munich City Data Search API',
        'version': '1.0.0',
        'endpoints': {
            '/api/search': 'Search across all datasets (params: q, category)',
            '/api/categories': 'Get all categories with counts',
            '/api/stats': 'Get statistics about the data',
            '/api/health': 'Health check'
        },
        'frontend': 'http://localhost:3000',
        'note': 'This is the backend API. Visit http://localhost:3000 for the web interface.'
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
