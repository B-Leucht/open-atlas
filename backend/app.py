from flask import Flask, jsonify, request
from flask_cors import CORS
import threading
import logging
from typing import List, Dict, Any, Optional
from functools import lru_cache
from datetime import datetime

# Configure logging to show INFO level messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)
CORS(app)

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
_vector_store = None

def get_vector_store():
    """Get vector store, auto-sync from database if empty"""
    global _vector_store
    if _vector_store is None:
        from chat.vector_store import VectorStore
        _vector_store = VectorStore()

        # Auto-sync if collection is empty
        try:
            collection = _vector_store.get_collection()
            if collection.count() == 0:
                logging.info("Vector store is empty, syncing from database...")
                count = _vector_store.sync_from_database(get_db())
                logging.info(f"Synced {count} datasets to vector store")
        except Exception as e:
            logging.warning(f"Could not auto-sync vector store: {e}")

    return _vector_store

def get_chat_agent():
    global _chat_agent
    if _chat_agent is None:
        from chat.agent import ChatAgent
        _chat_agent = ChatAgent(db=get_db(), vector_store=get_vector_store())
    return _chat_agent

# ============================================================================
# General Endpoints
# ============================================================================

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


@app.route('/api/v2/datasets/search', methods=['GET'])
def search_datasets():
    """
    Semantic search over datasets using vector store.

    Params:
        q: Search query (required)
        limit: Max results (default 20, max 100)
        district_only: If 'true', only return district-specific datasets
        geo_only: If 'true', only return datasets with geometry

    Returns datasets ranked by semantic relevance with scores.
    """
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'success': False, 'error': 'Query parameter q is required'}), 400

        limit = min(request.args.get('limit', 20, type=int), 100)
        district_only = request.args.get('district_only', 'false') == 'true'
        geo_only = request.args.get('geo_only', 'false') == 'true'

        # Build filters for vector store
        filters = {}
        if district_only:
            filters['is_district_specific'] = True
        if geo_only:
            filters['has_geometry'] = True

        # Search using vector store (semantic search)
        vector_store = get_vector_store()
        results = vector_store.search(
            query=query,
            n_results=limit,
            filters=filters if filters else None
        )

        # Enrich results with full dataset info from database
        db = get_db()
        enriched_results = []

        for hit in results:
            dataset_id = hit.get('id')
            if not dataset_id:
                continue

            # Get full dataset from database
            dataset = db.get_dataset_by_external_id('munich', dataset_id)
            if dataset:
                result = dataset.to_dict()
                # Add search metadata
                result['_search_score'] = hit.get('_distance', 0)
                enriched_results.append(result)
            else:
                # Fallback to vector store metadata
                enriched_results.append({
                    'id': dataset_id,
                    'external_id': dataset_id,
                    'title': hit.get('title', ''),
                    'description': hit.get('description', ''),
                    'has_geometry': hit.get('has_geometry', False),
                    'is_district_specific': hit.get('is_district_specific', False),
                    '_search_score': hit.get('_distance', 0)
                })

        return jsonify({
            'success': True,
            'query': query,
            'count': len(enriched_results),
            'datasets': enriched_results
        })

    except Exception as e:
        logging.error(f"Search error: {e}")
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

    Returns structured response including:
    - answer: The text response
    - query_type: "single_dataset", "multi_dataset", or "index_creation"
    - index_result: Full index data (if index_creation query)
    - geo_data: Geographic data for map display (if available)
    """
    try:
        data = request.get_json()
        if not data or not data.get('query'):
            return jsonify({'success': False, 'error': 'Query is required'}), 400

        query = data['query'].strip()
        if not query:
            return jsonify({'success': False, 'error': 'Query cannot be empty'}), 400

        agent = get_chat_agent()
        result = agent.query(query)

        # Build response with structured data
        response = {
            'success': True,
            'query': query,
            'answer': result.get('answer', ''),
            'query_type': result.get('query_type', 'single_dataset'),
        }

        # Include index result if available (for map visualization)
        if result.get('index_result'):
            response['index_result'] = result['index_result']
            response['suggested_index'] = result.get('suggested_index')

        # Include geographic data if available
        if result.get('geo_data'):
            response['geo_data'] = result['geo_data']

        return jsonify(response)

    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/chat/sync-vectors', methods=['POST'])
def sync_vector_store():
    """Sync vector store from local database"""
    try:
        from chat.vector_store import VectorStore

        # Check if we should clear first (e.g., after changing embedding models)
        clear_first = request.args.get('clear', 'false') == 'true'

        store = VectorStore()

        if clear_first:
            store.clear()
            logging.info("Cleared vector store before sync")

        count = store.sync_from_database(get_db())

        return jsonify({
            'success': True,
            'message': f'Synced {count} datasets to vector store',
            'count': count,
            'cleared': clear_first
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
        'version': '7.0.0',
        'endpoints': {
            'General': {
                'GET /api/health': 'Health check'
            },
            'Districts': {
                'GET /api/districts': 'Get all districts as GeoJSON',
                'GET /api/districts/:id': 'Get specific district',
                'GET /api/districts/:id/datasets': 'Get datasets in district',
                'GET /api/districts/stats': 'Get district statistics',
                'GET /api/districts/aggregate': 'Aggregate dataset by district (params: dataset, column, agg)'
            },
            'Datasets': {
                'GET /api/v2/datasets': 'List datasets (params: source, geo, district_specific, limit)',
                'GET /api/v2/datasets/search': 'Semantic search (params: q, limit, district_only, geo_only)',
                'GET /api/v2/datasets/:id': 'Get dataset details',
                'GET /api/v2/datasets/:id/features': 'Get dataset features as GeoJSON',
                'GET /api/v2/stats': 'Get local database statistics'
            },
            'Spatial Queries': {
                'GET /api/v2/features/near': 'Features near point (params: lat, lon, radius, dataset, limit)',
                'GET /api/v2/features/in-district/:id': 'Features in district'
            },
            'Indices': {
                'GET /api/indices/presets': 'List available preset indices',
                'GET /api/indices/presets/:id': 'Get preset details',
                'GET /api/indices/calculate/:preset_id': 'Calculate preset index',
                'POST /api/indices/calculate': 'Calculate custom index',
                'GET /api/indices/datasets': 'List datasets for index building',
                'GET /api/indices/datasets/:id/columns': 'Get dataset columns'
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
        'data_source': 'Open Data München (Local Database)'
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
