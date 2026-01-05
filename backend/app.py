from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import requests
import csv
import io
import threading
from typing import List, Dict, Any, Optional
from functools import lru_cache
from datetime import datetime

app = Flask(__name__)
CORS(app)

# CKAN API base URL
CKAN_API_BASE = "https://opendata.muenchen.de/api/3/action"

# Initialize data layer (lazy loading)
_db = None
_district_service = None
_data_sync = None

def get_db():
    global _db
    if _db is None:
        from data.database import Database
        _db = Database()
    return _db

def get_district_service():
    global _district_service
    if _district_service is None:
        from data.districts import DistrictService
        _district_service = DistrictService(get_db())
    return _district_service

def get_data_sync():
    global _data_sync
    if _data_sync is None:
        from data.sync import DataSync
        _data_sync = DataSync(get_db())
    return _data_sync

# Chat agent (lazy loading)
_chat_agent = None

def get_chat_agent():
    global _chat_agent
    if _chat_agent is None:
        from chat.agent import ChatAgent
        from chat.vector_store import VectorStore
        _chat_agent = ChatAgent(db=get_db(), vector_store=VectorStore())
    return _chat_agent

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
    """Convert CSV content to GeoJSON format (supports data without coordinates)"""
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        if not rows:
            return {"type": "FeatureCollection", "features": []}

        headers = list(rows[0].keys())
        coords = detect_coordinate_columns(headers)
        has_coords = coords['lat'] and coords['lon']

        features = []
        for row in rows:
            try:
                geometry = None
                properties = dict(row)

                if has_coords:
                    lat_str = row.get(coords['lat'], '').strip()
                    lon_str = row.get(coords['lon'], '').strip()

                    if lat_str and lon_str:
                        try:
                            from data.parsers import parse_german_number
                            lat = parse_german_number(lat_str)
                            lon = parse_german_number(lon_str)
                            if lat is not None and lon is not None:
                                geometry = {
                                    "type": "Point",
                                    "coordinates": [lon, lat]
                                }
                                # Remove coord columns from properties
                                properties = {k: v for k, v in row.items() if k not in [coords['lat'], coords['lon']]}
                        except ValueError:
                            pass

                feature = {
                    "type": "Feature",
                    "geometry": geometry,
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

# ============================================================================
# District Endpoints (New Data Layer)
# ============================================================================

@app.route('/api/districts', methods=['GET'])
def get_districts():
    """Get all districts with boundaries as GeoJSON"""
    try:
        source_id = request.args.get('source', 'munich')
        service = get_district_service()
        geojson = service.get_districts_geojson(source_id)

        return jsonify({
            'success': True,
            'count': len(geojson.get('features', [])),
            'data': geojson
        })
    except Exception as e:
        print(f"Error fetching districts: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/districts/<district_id>', methods=['GET'])
def get_district(district_id):
    """Get a specific district"""
    try:
        service = get_district_service()
        district = service.get_district(district_id)

        if not district:
            return jsonify({'success': False, 'error': 'District not found'}), 404

        return jsonify({
            'success': True,
            'data': district.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/districts/<district_id>/datasets', methods=['GET'])
def get_district_datasets(district_id):
    """Get datasets that have features in a specific district"""
    try:
        db = get_db()

        # Get features in this district and their datasets
        features = db.get_features(district_id=district_id, limit=1)
        if not features:
            return jsonify({'success': True, 'datasets': []})

        # Get unique dataset IDs
        dataset_ids = set()
        all_features = db.get_features(district_id=district_id, limit=10000)
        for f in all_features:
            dataset_ids.add(f.dataset_id)

        # Get dataset metadata
        datasets = []
        for ds_id in dataset_ids:
            ds = db.get_dataset(ds_id)
            if ds:
                datasets.append({
                    'id': ds.id,
                    'title': ds.title,
                    'feature_count': len([f for f in all_features if f.dataset_id == ds_id])
                })

        return jsonify({'success': True, 'datasets': datasets})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/districts/stats', methods=['GET'])
def get_district_stats():
    """Get district statistics"""
    try:
        source_id = request.args.get('source', 'munich')
        service = get_district_service()
        stats = service.get_district_statistics(source_id)
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/districts/aggregate', methods=['GET'])
def aggregate_by_district():
    """
    Aggregate dataset values by district for choropleth visualization.

    Params:
        dataset: Dataset ID (external_id from CKAN)
        column: Column name to aggregate
        agg: Aggregation function (count, sum, avg, min, max) - default: count

    Returns:
        {district_number: aggregated_value, ...}
    """
    try:
        dataset_id = request.args.get('dataset')
        column = request.args.get('column')
        agg_func = request.args.get('agg', 'count').lower()

        if not dataset_id:
            return jsonify({'success': False, 'error': 'dataset parameter required'}), 400

        db = get_db()

        # Find dataset - try multiple methods
        ds = None

        # Try by full ID first
        ds = db.get_dataset(dataset_id)

        # Try by external_id
        if not ds:
            ds = db.get_dataset_by_external_id('munich', dataset_id)

        # Try search
        if not ds:
            datasets = db.search_datasets(dataset_id, limit=1)
            if datasets:
                ds = datasets[0]

        if not ds:
            return jsonify({
                'success': False,
                'error': f'Dataset not found: {dataset_id}. Make sure to run sync first.'
            }), 404

        # Get features for this dataset
        features = db.get_features(dataset_id=ds.id, limit=50000)

        if not features:
            # No features synced - try to provide helpful message
            return jsonify({
                'success': False,
                'error': f'No features synced for this dataset. Run POST /api/sync/start to sync data.',
                'dataset_title': ds.title
            }), 404

        # Aggregate by district
        district_data = {}
        for f in features:
            district_num = None
            props = f.properties or {}

            # Try to find district from feature's district_id or properties
            if f.district_id:
                # Extract number from district_id like "munich_district_04"
                parts = f.district_id.split('_')
                if parts:
                    district_num = parts[-1]

            # Or look for district column in properties
            if not district_num:
                # First try numeric district columns
                for key in ['stadtbezirksnummer', 'sb_nummer', 'bezirksnummer', 'bezirks_nr']:
                    if key in props:
                        val = str(props[key]).strip()
                        # Handle numeric values - pad to 2 digits
                        try:
                            district_num = str(int(val)).zfill(2)
                            break
                        except ValueError:
                            continue

                # Then try _district_value from parser
                if not district_num and '_district_value' in props:
                    val = str(props['_district_value']).strip()
                    try:
                        district_num = str(int(val)).zfill(2)
                    except ValueError:
                        pass

            if not district_num:
                continue

            # Initialize district
            if district_num not in district_data:
                district_data[district_num] = {'values': [], 'count': 0}

            district_data[district_num]['count'] += 1

            # Get value for aggregation
            if column and column in props:
                from data.parsers import parse_german_number
                val = parse_german_number(props[column])
                if val is not None:
                    district_data[district_num]['values'].append(val)

        # Calculate aggregates
        result = {}
        for district_num, data in district_data.items():
            if agg_func == 'count':
                result[district_num] = data['count']
            elif data['values']:
                if agg_func == 'sum':
                    result[district_num] = sum(data['values'])
                elif agg_func == 'avg':
                    result[district_num] = sum(data['values']) / len(data['values'])
                elif agg_func == 'min':
                    result[district_num] = min(data['values'])
                elif agg_func == 'max':
                    result[district_num] = max(data['values'])
                else:
                    result[district_num] = data['count']
            else:
                result[district_num] = data['count']

        return jsonify({
            'success': True,
            'dataset': dataset_id,
            'column': column,
            'aggregation': agg_func,
            'data': result
        })

    except Exception as e:
        print(f"Aggregation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# Composite Index Endpoints
# ============================================================================

_index_calculator = None

def get_index_calculator():
    global _index_calculator
    if _index_calculator is None:
        from data.indices import IndexCalculator
        _index_calculator = IndexCalculator(get_db())
    return _index_calculator

@app.route('/api/indices/presets', methods=['GET'])
def get_index_presets():
    """Get available preset indices"""
    try:
        calc = get_index_calculator()
        presets = calc.get_presets()
        return jsonify({
            'success': True,
            'presets': presets
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/indices/presets/<preset_id>', methods=['GET'])
def get_index_preset_details(preset_id):
    """Get details about a specific preset"""
    try:
        calc = get_index_calculator()
        details = calc.get_preset_details(preset_id)
        if not details:
            return jsonify({'success': False, 'error': 'Preset not found'}), 404
        return jsonify({
            'success': True,
            'preset': details
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/indices/calculate/<preset_id>', methods=['GET'])
def calculate_preset_index(preset_id):
    """Calculate a preset index"""
    try:
        calc = get_index_calculator()
        year = request.args.get('year', type=int)
        result = calc.calculate_preset(preset_id, year)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/indices/calculate', methods=['POST'])
def calculate_custom_index():
    """Calculate a custom composite index"""
    try:
        from data.indices import IndexComponent, NormalizationType

        calc = get_index_calculator()
        data = request.json

        if not data or 'components' not in data:
            return jsonify({'success': False, 'error': 'Missing components'}), 400

        components = []
        for c in data['components']:
            norm_type = NormalizationType(c.get('normalize', 'minmax'))
            # Support both dataset_id (for direct lookup) and dataset_pattern
            dataset_ref = c.get('dataset_id') or c.get('dataset_pattern', '')
            components.append(IndexComponent(
                dataset_pattern=dataset_ref,
                column=c.get('column'),
                weight=float(c.get('weight', 1.0)),
                aggregation=c.get('aggregation', 'count'),
                normalize=norm_type,
                label=c.get('label', '')
            ))

        year = data.get('year')
        name = data.get('name', 'Custom Index')

        result = calc.calculate_index(components, year, name)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/indices/datasets', methods=['GET'])
def get_index_datasets():
    """Get datasets available for building custom indices"""
    try:
        calc = get_index_calculator()
        datasets = calc.get_available_datasets()
        return jsonify({
            'success': True,
            'datasets': datasets
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/indices/datasets/<dataset_id>/columns', methods=['GET'])
def get_dataset_columns(dataset_id):
    """Get numeric columns available for aggregation in a dataset"""
    try:
        db = get_db()
        features = db.get_features(dataset_id=dataset_id, limit=10)

        if not features:
            return jsonify({'success': True, 'columns': []})

        # Collect all property keys and check if they're numeric
        numeric_columns = set()
        all_columns = set()

        for f in features:
            props = f.properties or {}
            for key, value in props.items():
                if key.startswith('_'):
                    continue
                all_columns.add(key)
                # Check if value is numeric
                if isinstance(value, (int, float)):
                    numeric_columns.add(key)
                elif isinstance(value, str):
                    try:
                        float(value.replace(',', '.'))
                        numeric_columns.add(key)
                    except:
                        pass

        return jsonify({
            'success': True,
            'columns': sorted(list(all_columns)),
            'numeric_columns': sorted(list(numeric_columns))
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# Enhanced Dataset Endpoints (Local DB)
# ============================================================================

@app.route('/api/v2/datasets', methods=['GET'])
def get_local_datasets():
    """Get datasets from local database (faster, supports filters)"""
    try:
        db = get_db()
        source_id = request.args.get('source', 'munich')
        has_geometry = request.args.get('geo')
        is_district = request.args.get('district_specific')
        limit = min(request.args.get('limit', 100, type=int), 1000)

        datasets = db.get_datasets(
            source_id=source_id,
            has_geometry=has_geometry == 'true' if has_geometry else None,
            is_district_specific=is_district == 'true' if is_district else None,
            limit=limit
        )

        return jsonify({
            'success': True,
            'count': len(datasets),
            'datasets': [d.to_dict() for d in datasets]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/v2/datasets/<dataset_id>', methods=['GET'])
def get_local_dataset(dataset_id):
    """Get a specific dataset from local database"""
    try:
        db = get_db()
        dataset = db.get_dataset(dataset_id)

        if not dataset:
            return jsonify({'success': False, 'error': 'Dataset not found'}), 404

        return jsonify({
            'success': True,
            'data': dataset.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/v2/datasets/<dataset_id>/features', methods=['GET'])
def get_dataset_features(dataset_id):
    """Get features for a dataset as GeoJSON"""
    try:
        db = get_db()
        limit = min(request.args.get('limit', 1000, type=int), 5000)
        district_id = request.args.get('district')

        geojson = db.get_features_geojson(
            dataset_id=dataset_id,
            district_id=district_id,
            limit=limit
        )

        return jsonify({
            'success': True,
            'count': len(geojson.get('features', [])),
            'data': geojson
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# Spatial Query Endpoints
# ============================================================================

@app.route('/api/v2/features/near', methods=['GET'])
def get_features_near():
    """Get features near a point"""
    try:
        lat = request.args.get('lat', type=float)
        lon = request.args.get('lon', type=float)
        radius = request.args.get('radius', 1.0, type=float)  # km
        dataset_id = request.args.get('dataset')
        limit = min(request.args.get('limit', 100, type=int), 500)

        if lat is None or lon is None:
            return jsonify({'success': False, 'error': 'lat and lon required'}), 400

        db = get_db()
        results = db.get_features_near(lat, lon, radius, dataset_id, limit)

        features = []
        for feature, distance in results:
            gj = feature.to_geojson_feature()
            gj['properties']['distance_km'] = round(distance, 3)
            features.append(gj)

        return jsonify({
            'success': True,
            'count': len(features),
            'center': {'lat': lat, 'lon': lon},
            'radius_km': radius,
            'data': {
                'type': 'FeatureCollection',
                'features': features
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/v2/features/in-district/<district_id>', methods=['GET'])
def get_features_in_district(district_id):
    """Get all features within a district"""
    try:
        db = get_db()
        dataset_id = request.args.get('dataset')
        limit = min(request.args.get('limit', 1000, type=int), 5000)

        geojson = db.get_features_geojson(
            dataset_id=dataset_id,
            district_id=district_id,
            limit=limit
        )

        return jsonify({
            'success': True,
            'district_id': district_id,
            'count': len(geojson.get('features', [])),
            'data': geojson
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# Sync Endpoints
# ============================================================================

@app.route('/api/sync/status', methods=['GET'])
def get_sync_status():
    """Get current sync status"""
    try:
        source_id = request.args.get('source', 'munich')
        sync = get_data_sync()
        status = sync.get_sync_status(source_id)

        if not status:
            return jsonify({
                'success': True,
                'status': 'never_synced',
                'message': 'No sync has been performed yet'
            })

        return jsonify({
            'success': True,
            'data': status.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/sync/districts', methods=['POST'])
def sync_districts():
    """Sync district boundaries"""
    try:
        source_id = request.args.get('source', 'munich')
        service = get_district_service()

        from data.models import MUNICH_DATA_SOURCE
        count = service.ingest_districts(MUNICH_DATA_SOURCE if source_id == 'munich' else None)

        return jsonify({
            'success': True,
            'message': f'Synced {count} districts',
            'count': count
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/sync/start', methods=['POST'])
def start_sync():
    """Start a full data sync (runs in background)"""
    try:
        source_id = request.args.get('source', 'munich')
        metadata_only = request.args.get('metadata_only', 'false') == 'true'
        max_datasets = request.args.get('max_datasets', type=int)

        sync = get_data_sync()

        # Check if already running
        status = sync.get_sync_status(source_id)
        if status and status.status == 'running':
            return jsonify({
                'success': False,
                'error': 'Sync already in progress',
                'current': status.current_dataset
            }), 409

        # Run in background thread
        def run_sync():
            from data.models import MUNICH_DATA_SOURCE
            sync.sync_source(
                MUNICH_DATA_SOURCE if source_id == 'munich' else None,
                sync_features=not metadata_only,
                max_datasets=max_datasets
            )

        thread = threading.Thread(target=run_sync, daemon=True)
        thread.start()

        return jsonify({
            'success': True,
            'message': 'Sync started in background',
            'metadata_only': metadata_only
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# Chat Endpoints
# ============================================================================

@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Send a natural language query to the AI agent.
    The agent finds relevant datasets and analyzes them.
    """
    try:
        data = request.get_json()
        if not data or not data.get('query'):
            return jsonify({'success': False, 'error': 'Query is required'}), 400

        query = data['query'].strip()
        if not query:
            return jsonify({'success': False, 'error': 'Query cannot be empty'}), 400

        agent = get_chat_agent()
        answer = agent.query(query)

        return jsonify({
            'success': True,
            'query': query,
            'answer': answer
        })

    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/chat/sync-vectors', methods=['POST'])
def sync_vector_store():
    """Sync vector store from local database"""
    try:
        from chat.vector_store import VectorStore
        store = VectorStore()
        count = store.sync_from_database(get_db())

        return jsonify({
            'success': True,
            'message': f'Synced {count} datasets to vector store',
            'count': count
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# Data Sources Endpoints
# ============================================================================

@app.route('/api/sources', methods=['GET'])
def get_data_sources():
    """Get all configured data sources"""
    try:
        db = get_db()
        sources = db.get_data_sources()
        return jsonify({
            'success': True,
            'sources': [s.to_dict() for s in sources]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# Enhanced Statistics
# ============================================================================

@app.route('/api/v2/stats', methods=['GET'])
def get_local_stats():
    """Get statistics from local database"""
    try:
        db = get_db()
        source_id = request.args.get('source', 'munich')
        stats = db.get_stats(source_id)

        # Add sync status
        sync = get_data_sync()
        sync_status = sync.get_sync_status(source_id)

        return jsonify({
            'success': True,
            'source': source_id,
            'stats': stats,
            'sync': sync_status.to_dict() if sync_status else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# Root Endpoint
# ============================================================================

@app.route('/')
def index():
    """Root endpoint"""
    return jsonify({
        'message': 'Munich Open Data API',
        'version': '6.0.0',
        'endpoints': {
            'Legacy (CKAN direct)': {
                'GET /api/search': 'Search across datasets (params: q, datasets[], lat, lon, limit)',
                'GET /api/datasets': 'List all datasets (params: q, limit)',
                'GET /api/datasets/search': 'Dataset autocomplete (params: q)',
                'GET /api/stats': 'Get statistics',
                'GET /api/health': 'Health check'
            },
            'Districts': {
                'GET /api/districts': 'Get all districts as GeoJSON',
                'GET /api/districts/:id': 'Get specific district',
                'GET /api/districts/:id/datasets': 'Get datasets in district',
                'GET /api/districts/stats': 'Get district statistics'
            },
            'Local Database (v2)': {
                'GET /api/v2/datasets': 'List datasets (params: source, geo, district_specific, limit)',
                'GET /api/v2/datasets/:id': 'Get dataset details',
                'GET /api/v2/datasets/:id/features': 'Get dataset features as GeoJSON',
                'GET /api/v2/stats': 'Get local database statistics'
            },
            'Spatial Queries': {
                'GET /api/v2/features/near': 'Features near point (params: lat, lon, radius, dataset, limit)',
                'GET /api/v2/features/in-district/:id': 'Features in district'
            },
            'Sync': {
                'GET /api/sync/status': 'Get sync status',
                'POST /api/sync/districts': 'Sync district boundaries',
                'POST /api/sync/start': 'Start full sync (params: metadata_only, max_datasets)'
            },
            'Chat (AI Agent)': {
                'POST /api/chat': 'Send query to AI agent (body: {query: string})',
                'POST /api/chat/sync-vectors': 'Sync vector store from database'
            },
            'Data Sources': {
                'GET /api/sources': 'List configured data sources'
            }
        },
        'data_source': 'Open Data München (CKAN API + Local Cache)'
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
