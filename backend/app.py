from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import requests
import csv
import io
from typing import List, Dict, Any, Optional
from functools import lru_cache

app = Flask(__name__)
CORS(app)

# CKAN API base URL
CKAN_API_BASE = "https://opendata.muenchen.de/api/3/action"

# ============================================================================
# CKAN API Functions
# ============================================================================

def detect_coordinate_columns(headers: List[str]) -> Dict[str, Optional[str]]:
    """Detect latitude and longitude columns in CSV headers"""
    headers_lower = [h.lower().strip() for h in headers]

    lat_patterns = ['lat', 'latitude', 'breitengrad', 'y', 'northing']
    lon_patterns = ['lon', 'lng', 'longitude', 'laengengrad', 'längengrad', 'x', 'easting']

    lat_col = None
    lon_col = None

    for i, h in enumerate(headers_lower):
        if not lat_col:
            for pattern in lat_patterns:
                if pattern == h or h.startswith(pattern):
                    lat_col = headers[i]
                    break

        if not lon_col:
            for pattern in lon_patterns:
                if pattern == h or h.startswith(pattern):
                    lon_col = headers[i]
                    break

    if not lat_col or not lon_col:
        for i, h in enumerate(headers_lower):
            if not lat_col:
                for pattern in lat_patterns:
                    if pattern in h:
                        lat_col = headers[i]
                        break

            if not lon_col:
                for pattern in lon_patterns:
                    if pattern in h:
                        lon_col = headers[i]
                        break

    return {'lat': lat_col, 'lon': lon_col}

def csv_to_geojson(csv_content: str, package_id: str) -> Dict[str, Any]:
    """Convert CSV content to GeoJSON format"""
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        if not rows:
            return {"type": "FeatureCollection", "features": []}

        headers = list(rows[0].keys())
        coords = detect_coordinate_columns(headers)

        if not coords['lat'] or not coords['lon']:
            return {"type": "FeatureCollection", "features": []}

        features = []
        for row in rows:
            try:
                lat_str = row.get(coords['lat'], '').strip()
                lon_str = row.get(coords['lon'], '').strip()

                if not lat_str or not lon_str:
                    continue

                lat = float(lat_str.replace(',', '.'))
                lon = float(lon_str.replace(',', '.'))

                properties = {k: v for k, v in row.items() if k not in [coords['lat'], coords['lon']]}

                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lon, lat]
                    },
                    "properties": properties
                }

                features.append(feature)
            except (ValueError, AttributeError):
                continue

        return {
            "type": "FeatureCollection",
            "features": features
        }

    except Exception as e:
        print(f"Error converting CSV to GeoJSON: {e}")
        return {"type": "FeatureCollection", "features": []}

@lru_cache(maxsize=100)
def fetch_ckan_dataset(package_id: str) -> Dict[str, Any]:
    """Fetch dataset from CKAN API and return GeoJSON data"""
    try:
        package_url = f"{CKAN_API_BASE}/package_show"
        params = {"id": package_id}

        response = requests.get(package_url, params=params, timeout=10)
        response.raise_for_status()

        package_data = response.json()

        if not package_data.get('success'):
            return {"type": "FeatureCollection", "features": []}

        resources = package_data.get('result', {}).get('resources', [])
        data_resource = None
        resource_format = None

        format_priority = ['geojson', 'json', 'csv']

        for fmt in format_priority:
            for resource in resources:
                if resource.get('format', '').lower() == fmt:
                    data_resource = resource
                    resource_format = fmt
                    break
            if data_resource:
                break

        if not data_resource:
            return {"type": "FeatureCollection", "features": []}

        data_url = data_resource.get('url')
        if not data_url:
            return {"type": "FeatureCollection", "features": []}

        data_response = requests.get(data_url, timeout=30)
        data_response.raise_for_status()

        if resource_format == 'csv':
            csv_content = data_response.text
            geojson_data = csv_to_geojson(csv_content, package_id)
        else:
            geojson_data = data_response.json()

        return geojson_data

    except Exception as e:
        print(f"Error fetching CKAN dataset {package_id}: {e}")
        return {"type": "FeatureCollection", "features": []}

# ============================================================================
# Helper Functions
# ============================================================================

def search_features(features: List[Dict], query: str) -> List[Dict]:
    """Search through features based on query string"""
    if not query or query.strip() == '':
        return features

    query_lower = query.lower().strip()
    results = []

    for feature in features:
        properties = feature.get('properties', {})
        searchable_text = ' '.join(
            str(v).lower() for v in properties.values() if v is not None
        )

        if query_lower in searchable_text:
            results.append(feature)

    return results

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km using Haversine formula"""
    from math import radians, sin, cos, sqrt, atan2

    R = 6371

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    return R * c

# ============================================================================
# Search Endpoint
# ============================================================================

@app.route('/api/search', methods=['GET'])
def global_search():
    """Search across datasets"""
    try:
        query = request.args.get('q', '')
        dataset_ids = request.args.getlist('datasets')
        lat = request.args.get('lat', type=float)
        lon = request.args.get('lon', type=float)
        limit = min(request.args.get('limit', 500, type=int), 2000)
        max_per_dataset = min(request.args.get('max_per_dataset', 200, type=int), 500)

        if not dataset_ids:
            return jsonify({
                'error': 'No datasets specified',
                'results': [],
                'total': 0
            })

        dataset_metadata = {}
        all_features = []

        for dataset_id in dataset_ids:
            try:
                # Fetch metadata
                pkg_url = f"{CKAN_API_BASE}/package_show"
                pkg_response = requests.get(pkg_url, params={'id': dataset_id}, timeout=5)
                if pkg_response.status_code == 200:
                    pkg_data = pkg_response.json()
                    if pkg_data.get('success'):
                        dataset_metadata[dataset_id] = {
                            'title': pkg_data['result'].get('title', dataset_id),
                            'name': pkg_data['result'].get('name', '')
                        }

                # Fetch data
                geojson_data = fetch_ckan_dataset(dataset_id)
                features = geojson_data.get('features', [])

                if len(features) > max_per_dataset:
                    step = len(features) / max_per_dataset
                    features = [features[int(i * step)] for i in range(max_per_dataset)]

                for feature in features:
                    feature['dataset_id'] = dataset_id

                all_features.extend(features)
            except Exception as e:
                print(f"Error loading dataset {dataset_id}: {e}")

        results = search_features(all_features, query)

        if lat and lon:
            for feature in results:
                if feature.get('geometry') and feature['geometry'].get('type') == 'Point':
                    coords = feature['geometry']['coordinates']
                    feature_lon, feature_lat = coords[0], coords[1]
                    if feature_lat and feature_lon:
                        distance = calculate_distance(lat, lon, feature_lat, feature_lon)
                        feature['distance_km'] = round(distance, 2)
            results = sorted(results, key=lambda x: x.get('distance_km', float('inf')))

        total_results = len(results)
        results = results[:limit]

        return jsonify({
            'query': query,
            'total': total_results,
            'count': len(results),
            'results': results,
            'dataset_metadata': dataset_metadata
        })

    except Exception as e:
        print(f"Error in global search: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================================
# Dataset Endpoints
# ============================================================================

@app.route('/api/datasets', methods=['GET'])
def list_datasets():
    """List all available datasets from CKAN"""
    try:
        query = request.args.get('q', '')
        limit = request.args.get('limit', 100, type=int)

        search_url = f"{CKAN_API_BASE}/package_search"
        params = {
            'q': query,
            'rows': min(limit, 1000),
            'fl': 'id,name,title,notes,num_resources'
        }

        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        if not data.get('success'):
            return jsonify({'error': 'CKAN API error'}), 500

        result = data.get('result', {})
        datasets = result.get('results', [])

        formatted_datasets = []
        for dataset in datasets:
            formatted_datasets.append({
                'id': dataset.get('id'),
                'name': dataset.get('name'),
                'title': dataset.get('title'),
                'description': dataset.get('notes', ''),
                'num_resources': dataset.get('num_resources', 0)
            })

        return jsonify({
            'count': result.get('count', 0),
            'datasets': formatted_datasets
        })

    except Exception as e:
        print(f"Error fetching datasets: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/datasets/search', methods=['GET'])
def search_datasets():
    """Search datasets by name/title for autocomplete"""
    query = request.args.get('q', '')

    if not query or len(query) < 2:
        return jsonify({'suggestions': []})

    try:
        search_url = f"{CKAN_API_BASE}/package_search"
        params = {
            'q': query,
            'rows': 20,
            'fl': 'id,name,title'
        }

        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        if not data.get('success'):
            return jsonify({'suggestions': []})

        datasets = data.get('result', {}).get('results', [])

        suggestions = []
        for dataset in datasets:
            suggestions.append({
                'id': dataset.get('id'),
                'name': dataset.get('name'),
                'title': dataset.get('title')
            })

        return jsonify({'suggestions': suggestions})

    except Exception as e:
        print(f"Error in dataset search: {e}")
        return jsonify({'suggestions': []})

# ============================================================================
# General Endpoints
# ============================================================================

@app.route('/api/stats', methods=['GET'])
def stats():
    """Get statistics about available datasets"""
    try:
        search_url = f"{CKAN_API_BASE}/package_search"
        params = {'rows': 0}

        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        total_datasets = data.get('result', {}).get('count', 0)

        return jsonify({
            'total_datasets': total_datasets,
            'api_base': CKAN_API_BASE
        })

    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})

@app.route('/')
def index():
    """Root endpoint"""
    return jsonify({
        'message': 'Munich Open Data API',
        'version': '5.0.0',
        'endpoints': {
            'GET /api/search': 'Search across datasets (params: q, datasets[], lat, lon, limit)',
            'GET /api/datasets': 'List all datasets (params: q, limit)',
            'GET /api/datasets/search': 'Dataset autocomplete (params: q)',
            'GET /api/stats': 'Get statistics',
            'GET /api/health': 'Health check'
        },
        'data_source': 'Open Data München (CKAN API)'
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
