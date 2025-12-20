from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import requests
import sqlite3
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from functools import lru_cache
from contextlib import contextmanager

app = Flask(__name__)
CORS(app)

# CKAN API base URL
CKAN_API_BASE = "https://opendata.muenchen.de/api/3/action"

# Database configuration
DATABASE = 'workspaces.db'

# ============================================================================
# Database Functions
# ============================================================================

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialize the database with required tables"""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                dataset_ids TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
    print("Database initialized successfully")

def get_workspace_by_id(workspace_id: str) -> Optional[Dict[str, Any]]:
    """Get a workspace by ID"""
    with get_db() as conn:
        cursor = conn.execute(
            'SELECT * FROM workspaces WHERE id = ?',
            (workspace_id,)
        )
        row = cursor.fetchone()

        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'description': row['description'],
                'dataset_ids': json.loads(row['dataset_ids']),
                'created_at': row['created_at'],
                'updated_at': row['updated_at']
            }
        return None

def create_workspace(name: str, dataset_ids: List[str], description: str = '') -> Dict[str, Any]:
    """Create a new workspace"""
    workspace_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        conn.execute(
            '''INSERT INTO workspaces (id, name, description, dataset_ids, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (workspace_id, name, description, json.dumps(dataset_ids), now, now)
        )
        conn.commit()

    return {
        'id': workspace_id,
        'name': name,
        'description': description,
        'dataset_ids': dataset_ids,
        'created_at': now,
        'updated_at': now
    }

def update_workspace(workspace_id: str, name: str = None, dataset_ids: List[str] = None, description: str = None) -> Optional[Dict[str, Any]]:
    """Update an existing workspace"""
    workspace = get_workspace_by_id(workspace_id)
    if not workspace:
        return None

    # Update only provided fields
    if name is not None:
        workspace['name'] = name
    if dataset_ids is not None:
        workspace['dataset_ids'] = dataset_ids
    if description is not None:
        workspace['description'] = description

    workspace['updated_at'] = datetime.utcnow().isoformat()

    with get_db() as conn:
        conn.execute(
            '''UPDATE workspaces
               SET name = ?, description = ?, dataset_ids = ?, updated_at = ?
               WHERE id = ?''',
            (workspace['name'], workspace['description'],
             json.dumps(workspace['dataset_ids']), workspace['updated_at'], workspace_id)
        )
        conn.commit()

    return workspace

def delete_workspace(workspace_id: str) -> bool:
    """Delete a workspace"""
    with get_db() as conn:
        cursor = conn.execute('DELETE FROM workspaces WHERE id = ?', (workspace_id,))
        conn.commit()
        return cursor.rowcount > 0

def list_workspaces() -> List[Dict[str, Any]]:
    """List all workspaces"""
    with get_db() as conn:
        cursor = conn.execute(
            'SELECT * FROM workspaces ORDER BY updated_at DESC'
        )
        rows = cursor.fetchall()

        return [{
            'id': row['id'],
            'name': row['name'],
            'description': row['description'],
            'dataset_ids': json.loads(row['dataset_ids']),
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        } for row in rows]

# ============================================================================
# CKAN API Functions
# ============================================================================

@lru_cache(maxsize=None)
def fetch_ckan_dataset(package_id: str) -> Dict[str, Any]:
    """Fetch dataset from CKAN API and return GeoJSON data"""
    try:
        # Get package metadata
        package_url = f"{CKAN_API_BASE}/package_show"
        params = {"id": package_id}

        print(f"Fetching package metadata for: {package_id}")
        response = requests.get(package_url, params=params, timeout=10)
        response.raise_for_status()

        package_data = response.json()

        if not package_data.get('success'):
            print(f"API returned unsuccessful response for {package_id}")
            return {"type": "FeatureCollection", "features": []}

        # Find GeoJSON resource
        resources = package_data.get('result', {}).get('resources', [])
        geojson_resource = None

        # Try to find GeoJSON format first, fall back to other formats
        for resource in resources:
            resource_format = resource.get('format', '').lower()
            if resource_format == 'geojson':
                geojson_resource = resource
                break

        # If no GeoJSON found, try JSON
        if not geojson_resource:
            for resource in resources:
                resource_format = resource.get('format', '').lower()
                if resource_format == 'json':
                    geojson_resource = resource
                    break

        if not geojson_resource:
            print(f"No GeoJSON/JSON resource found for {package_id}")
            print(f"Available formats: {[r.get('format') for r in resources]}")
            return {"type": "FeatureCollection", "features": []}

        # Download GeoJSON data
        data_url = geojson_resource.get('url')
        if not data_url:
            print(f"No URL found for GeoJSON resource in {package_id}")
            return {"type": "FeatureCollection", "features": []}

        print(f"Downloading GeoJSON from: {data_url}")
        data_response = requests.get(data_url, timeout=30)
        data_response.raise_for_status()

        geojson_data = data_response.json()
        return geojson_data

    except requests.exceptions.RequestException as e:
        print(f"Error fetching CKAN dataset {package_id}: {e}")
        return {"type": "FeatureCollection", "features": []}
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON for {package_id}: {e}")
        return {"type": "FeatureCollection", "features": []}
    except Exception as e:
        print(f"Unexpected error loading {package_id}: {e}")
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
        from math import pi

        k0 = 0.9996
        false_easting = 500000
        false_northing = 0

        x = x - false_easting
        lon = 11.5 + (x / 111320)
        lat = y / 111320 - 1000

        return lat, lon
    except:
        return None, None

# ============================================================================
# Workspace Endpoints
# ============================================================================

@app.route('/api/workspaces', methods=['GET'])
def get_workspaces():
    """Get all workspaces"""
    try:
        workspaces = list_workspaces()
        return jsonify({
            'count': len(workspaces),
            'workspaces': workspaces
        })
    except Exception as e:
        print(f"Error listing workspaces: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/workspaces', methods=['POST'])
def create_new_workspace():
    """Create a new workspace"""
    try:
        data = request.get_json()

        name = data.get('name')
        dataset_ids = data.get('dataset_ids', [])
        description = data.get('description', '')

        if not name:
            return jsonify({'error': 'Workspace name is required'}), 400

        if not dataset_ids:
            return jsonify({'error': 'At least one dataset ID is required'}), 400

        workspace = create_workspace(name, dataset_ids, description)
        return jsonify(workspace), 201

    except Exception as e:
        print(f"Error creating workspace: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/workspaces/<workspace_id>', methods=['GET'])
def get_workspace(workspace_id):
    """Get a specific workspace"""
    try:
        workspace = get_workspace_by_id(workspace_id)

        if not workspace:
            return jsonify({'error': 'Workspace not found'}), 404

        return jsonify(workspace)

    except Exception as e:
        print(f"Error getting workspace: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/workspaces/<workspace_id>', methods=['PUT'])
def update_existing_workspace(workspace_id):
    """Update a workspace"""
    try:
        data = request.get_json()

        name = data.get('name')
        dataset_ids = data.get('dataset_ids')
        description = data.get('description')

        workspace = update_workspace(workspace_id, name, dataset_ids, description)

        if not workspace:
            return jsonify({'error': 'Workspace not found'}), 404

        return jsonify(workspace)

    except Exception as e:
        print(f"Error updating workspace: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/workspaces/<workspace_id>', methods=['DELETE'])
def delete_existing_workspace(workspace_id):
    """Delete a workspace"""
    try:
        success = delete_workspace(workspace_id)

        if not success:
            return jsonify({'error': 'Workspace not found'}), 404

        return jsonify({'success': True, 'message': 'Workspace deleted'})

    except Exception as e:
        print(f"Error deleting workspace: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/workspaces/<workspace_id>/load', methods=['GET'])
def load_workspace_data(workspace_id):
    """Load all data from a workspace's datasets"""
    try:
        workspace = get_workspace_by_id(workspace_id)

        if not workspace:
            return jsonify({'error': 'Workspace not found'}), 404

        dataset_ids = workspace['dataset_ids']

        # Fetch all datasets
        loaded_data = []
        errors = []

        for dataset_id in dataset_ids:
            try:
                geojson_data = fetch_ckan_dataset(dataset_id)
                features = geojson_data.get('features', [])

                # Add dataset_id to each feature
                for feature in features:
                    feature['dataset_id'] = dataset_id

                loaded_data.extend(features)

            except Exception as e:
                print(f"Error loading dataset {dataset_id}: {e}")
                errors.append({
                    'dataset_id': dataset_id,
                    'error': str(e)
                })

        return jsonify({
            'workspace_id': workspace_id,
            'workspace_name': workspace['name'],
            'count': len(loaded_data),
            'features': loaded_data,
            'errors': errors
        })

    except Exception as e:
        print(f"Error loading workspace data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/workspaces/<workspace_id>/search', methods=['GET'])
def search_workspace(workspace_id):
    """Search within a workspace's datasets"""
    try:
        workspace = get_workspace_by_id(workspace_id)

        if not workspace:
            return jsonify({'error': 'Workspace not found'}), 404

        query = request.args.get('q', '')
        lat = request.args.get('lat', type=float)
        lon = request.args.get('lon', type=float)

        print(f"Searching workspace '{workspace['name']}' - Query: '{query}', Lat: {lat}, Lon: {lon}")

        dataset_ids = workspace['dataset_ids']

        # Load all datasets from workspace
        all_features = []
        for dataset_id in dataset_ids:
            try:
                geojson_data = fetch_ckan_dataset(dataset_id)
                features = geojson_data.get('features', [])

                # Add dataset_id to each feature
                for feature in features:
                    feature['dataset_id'] = dataset_id

                all_features.extend(features)
            except Exception as e:
                print(f"Error loading dataset {dataset_id}: {e}")

        print(f"Total features loaded from workspace: {len(all_features)}")

        # Search through features
        results = search_features(all_features, query)
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
            'workspace_id': workspace_id,
            'workspace_name': workspace['name'],
            'query': query,
            'count': len(results),
            'results': results
        })

    except Exception as e:
        print(f"Error searching workspace: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================================================
# Dataset Endpoints (kept for backward compatibility)
# ============================================================================

@app.route('/api/datasets', methods=['GET'])
def list_datasets():
    """List all available datasets from CKAN"""
    try:
        query = request.args.get('q', '')
        limit = request.args.get('limit', 1000, type=int)

        search_url = f"{CKAN_API_BASE}/package_search"
        params = {
            'q': query,
            'rows': min(limit, 1000),
            'fl': 'id,name,title,notes,num_resources'
        }

        print(f"Searching datasets with query: '{query}'")
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        if not data.get('success'):
            return jsonify({'error': 'CKAN API returned unsuccessful response'}), 500

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

    except requests.exceptions.RequestException as e:
        print(f"Error fetching datasets: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
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
    """Get statistics about available datasets and workspaces"""
    try:
        # Get total count of datasets
        search_url = f"{CKAN_API_BASE}/package_search"
        params = {'rows': 0}

        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        total_datasets = data.get('result', {}).get('count', 0)

        # Get workspace count
        workspaces = list_workspaces()
        workspace_count = len(workspaces)

        return jsonify({
            'total_datasets': total_datasets,
            'total_workspaces': workspace_count,
            'api_base': CKAN_API_BASE
        })

    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'database': 'connected'})

@app.route('/')
def index():
    """Root endpoint with API documentation"""
    return jsonify({
        'message': 'Munich City Data Search API - CKAN Integration with Workspaces',
        'version': '3.0.0',
        'endpoints': {
            'workspaces': {
                'GET /api/workspaces': 'List all workspaces',
                'POST /api/workspaces': 'Create new workspace (body: {name, dataset_ids, description})',
                'GET /api/workspaces/<id>': 'Get workspace details',
                'PUT /api/workspaces/<id>': 'Update workspace',
                'DELETE /api/workspaces/<id>': 'Delete workspace',
                'GET /api/workspaces/<id>/load': 'Load all data from workspace',
                'GET /api/workspaces/<id>/search': 'Search within workspace (params: q, lat, lon)'
            },
            'datasets': {
                'GET /api/datasets': 'List all available datasets (params: q, limit)',
                'GET /api/datasets/search': 'Search datasets for autocomplete (params: q)'
            },
            'general': {
                'GET /api/stats': 'Get statistics',
                'GET /api/health': 'Health check'
            }
        },
        'data_source': 'Open Data München (CKAN API)',
        'features': [
            'Workspace-based dataset management',
            'Persistent storage with SQLite',
            'Multi-frontend support',
            'Shareable workspace URLs'
        ]
    })

# ============================================================================
# Application Initialization
# ============================================================================

if __name__ == '__main__':
    # Initialize database on startup
    init_db()

    # Run the app
    app.run(debug=True, host='0.0.0.0', port=5001)
