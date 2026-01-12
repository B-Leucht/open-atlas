"""
Database Layer for Open Atlas
Uses SQLite with SpatiaLite extension for spatial queries
Designed to support multiple data sources
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from .models import (
    DataSource, Dataset, DatasetResource, District, Feature, SyncStatus,
    MUNICH_DATA_SOURCE
)

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "openatlas.db"


class Database:
    """
    SQLite database with optional SpatiaLite extension for geographic queries.
    Supports multiple data sources (cities) with districts and features.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DEFAULT_DB_PATH)
        self._ensure_directory()
        self._spatialite_available = False
        self._init_database()

    def _ensure_directory(self):
        """Ensure the database directory exists"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _load_spatialite(self, conn: sqlite3.Connection) -> bool:
        """Try to load SpatiaLite extension (optional - falls back to pure Python)"""
        try:
            # Check if extension loading is supported
            if not hasattr(conn, 'enable_load_extension'):
                return False

            conn.enable_load_extension(True)
            # Try common SpatiaLite library paths
            spatialite_paths = [
                'mod_spatialite',
                'mod_spatialite.so',
                'mod_spatialite.dylib',
                '/usr/local/lib/mod_spatialite.dylib',
                '/opt/homebrew/lib/mod_spatialite.dylib',
                '/usr/lib/x86_64-linux-gnu/mod_spatialite.so',
            ]
            for path in spatialite_paths:
                try:
                    conn.load_extension(path)
                    logger.debug(f"Loaded SpatiaLite from {path}")
                    return True
                except sqlite3.OperationalError:
                    continue
            return False
        except AttributeError:
            # enable_load_extension not available - Python compiled without it
            return False
        except Exception:
            # SpatiaLite not available - use pure Python fallback
            return False

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection with SpatiaLite if available"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        if self._spatialite_available:
            self._load_spatialite(conn)

        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_database(self):
        """Initialize database schema"""
        with self.get_connection() as conn:
            # Try loading SpatiaLite
            self._spatialite_available = self._load_spatialite(conn)

            cursor = conn.cursor()

            # Data Sources table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS data_sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    api_base_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    default_crs TEXT DEFAULT 'EPSG:4326',
                    bounds TEXT,
                    config TEXT,
                    enabled INTEGER DEFAULT 1,
                    last_sync TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Districts table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS districts (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    number TEXT NOT NULL,
                    name TEXT NOT NULL,
                    geometry TEXT,
                    centroid_lat REAL,
                    centroid_lon REAL,
                    area_sqm REAL,
                    properties TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES data_sources(id),
                    UNIQUE(source_id, number)
                )
            ''')

            # Datasets table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    resources TEXT,
                    tags TEXT,
                    groups TEXT,
                    organization TEXT,
                    license TEXT,
                    has_geometry INTEGER DEFAULT 0,
                    geometry_types TEXT,
                    is_district_specific INTEGER DEFAULT 0,
                    district_column TEXT,
                    feature_count INTEGER DEFAULT 0,
                    last_modified TEXT,
                    last_synced TEXT,
                    sync_status TEXT DEFAULT 'pending',
                    sync_error TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES data_sources(id),
                    UNIQUE(source_id, external_id)
                )
            ''')

            # Features table (stores individual geographic features)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS features (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    geometry TEXT,
                    geometry_type TEXT,
                    properties TEXT,
                    district_id TEXT,
                    centroid_lat REAL,
                    centroid_lon REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (dataset_id) REFERENCES datasets(id),
                    FOREIGN KEY (source_id) REFERENCES data_sources(id),
                    FOREIGN KEY (district_id) REFERENCES districts(id)
                )
            ''')

            # Sync status table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_status (
                    source_id TEXT PRIMARY KEY,
                    total_datasets INTEGER DEFAULT 0,
                    synced_datasets INTEGER DEFAULT 0,
                    failed_datasets INTEGER DEFAULT 0,
                    total_features INTEGER DEFAULT 0,
                    started_at TEXT,
                    completed_at TEXT,
                    status TEXT DEFAULT 'idle',
                    current_dataset TEXT,
                    errors TEXT,
                    FOREIGN KEY (source_id) REFERENCES data_sources(id)
                )
            ''')

            # Create indexes for common queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_districts_source ON districts(source_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_datasets_source ON datasets(source_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_datasets_has_geo ON datasets(has_geometry)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_features_dataset ON features(dataset_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_features_district ON features(district_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_features_coords ON features(centroid_lat, centroid_lon)')

            # Initialize with Munich data source if not exists
            cursor.execute('SELECT id FROM data_sources WHERE id = ?', (MUNICH_DATA_SOURCE.id,))
            if not cursor.fetchone():
                self.upsert_data_source(MUNICH_DATA_SOURCE)

            conn.commit()
            logger.debug(f"Database initialized at {self.db_path}")

    # =========================================================================
    # Data Source Operations
    # =========================================================================

    def upsert_data_source(self, source: DataSource) -> None:
        """Insert or update a data source"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO data_sources
                (id, name, display_name, api_base_url, source_type, default_crs, bounds, config, enabled, last_sync, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                source.id,
                source.name,
                source.display_name,
                source.api_base_url,
                source.source_type.value,
                source.default_crs,
                json.dumps(source.bounds) if source.bounds else None,
                json.dumps(source.config) if source.config else None,
                1 if source.enabled else 0,
                source.last_sync.isoformat() if source.last_sync else None,
                datetime.utcnow().isoformat()
            ))

    def get_data_sources(self, enabled_only: bool = True) -> List[DataSource]:
        """Get all data sources"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if enabled_only:
                cursor.execute('SELECT * FROM data_sources WHERE enabled = 1')
            else:
                cursor.execute('SELECT * FROM data_sources')

            sources = []
            for row in cursor.fetchall():
                sources.append(self._row_to_data_source(row))
            return sources

    def get_data_source(self, source_id: str) -> Optional[DataSource]:
        """Get a specific data source"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM data_sources WHERE id = ?', (source_id,))
            row = cursor.fetchone()
            return self._row_to_data_source(row) if row else None

    def _row_to_data_source(self, row: sqlite3.Row) -> DataSource:
        from .models import DataSourceType
        return DataSource(
            id=row['id'],
            name=row['name'],
            display_name=row['display_name'],
            api_base_url=row['api_base_url'],
            source_type=DataSourceType(row['source_type']),
            default_crs=row['default_crs'],
            bounds=json.loads(row['bounds']) if row['bounds'] else None,
            config=json.loads(row['config']) if row['config'] else {},
            enabled=bool(row['enabled']),
            last_sync=datetime.fromisoformat(row['last_sync']) if row['last_sync'] else None
        )

    # =========================================================================
    # District Operations
    # =========================================================================

    def upsert_district(self, district: District) -> None:
        """Insert or update a district"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO districts
                (id, source_id, number, name, geometry, centroid_lat, centroid_lon, area_sqm, properties, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                district.id,
                district.source_id,
                district.number,
                district.name,
                json.dumps(district.geometry) if district.geometry else None,
                district.centroid_lat,
                district.centroid_lon,
                district.area_sqm,
                json.dumps(district.properties) if district.properties else None,
                datetime.utcnow().isoformat()
            ))

    def upsert_districts_batch(self, districts: List[District]) -> None:
        """Batch insert/update districts"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT OR REPLACE INTO districts
                (id, source_id, number, name, geometry, centroid_lat, centroid_lon, area_sqm, properties, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (
                    d.id, d.source_id, d.number, d.name,
                    json.dumps(d.geometry) if d.geometry else None,
                    d.centroid_lat, d.centroid_lon, d.area_sqm,
                    json.dumps(d.properties) if d.properties else None,
                    datetime.utcnow().isoformat()
                ) for d in districts
            ])

    def get_districts(self, source_id: str = None) -> List[District]:
        """Get all districts for a source"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if source_id:
                cursor.execute('SELECT * FROM districts WHERE source_id = ? ORDER BY number', (source_id,))
            else:
                cursor.execute('SELECT * FROM districts ORDER BY source_id, number')

            districts = []
            for row in cursor.fetchall():
                districts.append(self._row_to_district(row))
            return districts

    def get_district(self, district_id: str) -> Optional[District]:
        """Get a specific district"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM districts WHERE id = ?', (district_id,))
            row = cursor.fetchone()
            return self._row_to_district(row) if row else None

    def get_district_by_number(self, source_id: str, number: str) -> Optional[District]:
        """Get district by number within a source"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM districts WHERE source_id = ? AND number = ?',
                (source_id, number)
            )
            row = cursor.fetchone()
            return self._row_to_district(row) if row else None

    def _row_to_district(self, row: sqlite3.Row) -> District:
        return District(
            id=row['id'],
            source_id=row['source_id'],
            number=row['number'],
            name=row['name'],
            geometry=json.loads(row['geometry']) if row['geometry'] else None,
            centroid_lat=row['centroid_lat'],
            centroid_lon=row['centroid_lon'],
            area_sqm=row['area_sqm'],
            properties=json.loads(row['properties']) if row['properties'] else {},
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.utcnow(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else datetime.utcnow()
        )

    def get_districts_geojson(self, source_id: str = None) -> Dict[str, Any]:
        """Get districts as GeoJSON FeatureCollection"""
        districts = self.get_districts(source_id)
        return {
            'type': 'FeatureCollection',
            'features': [d.to_geojson_feature() for d in districts]
        }

    # =========================================================================
    # Dataset Operations
    # =========================================================================

    def upsert_dataset(self, dataset: Dataset) -> None:
        """Insert or update a dataset"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO datasets
                (id, source_id, external_id, title, description, resources, tags, groups,
                 organization, license, has_geometry, geometry_types, is_district_specific,
                 district_column, feature_count, last_modified, last_synced, sync_status,
                 sync_error, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                dataset.id,
                dataset.source_id,
                dataset.external_id,
                dataset.title,
                dataset.description,
                json.dumps([r.to_dict() for r in dataset.resources]),
                json.dumps(dataset.tags),
                json.dumps(dataset.groups),
                dataset.organization,
                dataset.license,
                1 if dataset.has_geometry else 0,
                json.dumps(dataset.geometry_types),
                1 if dataset.is_district_specific else 0,
                dataset.district_column,
                dataset.feature_count,
                dataset.last_modified.isoformat() if dataset.last_modified else None,
                dataset.last_synced.isoformat() if dataset.last_synced else None,
                dataset.sync_status,
                dataset.sync_error,
                json.dumps(dataset.metadata),
                datetime.utcnow().isoformat()
            ))

    def get_datasets(self, source_id: str = None, has_geometry: bool = None,
                     is_district_specific: bool = None, limit: int = None) -> List[Dataset]:
        """Get datasets with optional filters"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = 'SELECT * FROM datasets WHERE 1=1'
            params = []

            if source_id:
                query += ' AND source_id = ?'
                params.append(source_id)
            if has_geometry is not None:
                query += ' AND has_geometry = ?'
                params.append(1 if has_geometry else 0)
            if is_district_specific is not None:
                query += ' AND is_district_specific = ?'
                params.append(1 if is_district_specific else 0)

            query += ' ORDER BY title'

            if limit:
                query += ' LIMIT ?'
                params.append(limit)

            cursor.execute(query, params)

            datasets = []
            for row in cursor.fetchall():
                datasets.append(self._row_to_dataset(row))
            return datasets

    def get_dataset(self, dataset_id: str) -> Optional[Dataset]:
        """Get a specific dataset"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM datasets WHERE id = ?', (dataset_id,))
            row = cursor.fetchone()
            return self._row_to_dataset(row) if row else None

    def get_dataset_by_external_id(self, source_id: str, external_id: str) -> Optional[Dataset]:
        """Get dataset by external ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM datasets WHERE source_id = ? AND external_id = ?',
                (source_id, external_id)
            )
            row = cursor.fetchone()
            return self._row_to_dataset(row) if row else None

    def search_datasets(self, query: str, source_id: str = None, limit: int = 50) -> List[Dataset]:
        """
        Search datasets by title, description, tags, and groups with fuzzy matching.
        Uses relevance scoring to return best matches first.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Split query into individual words for better fuzzy matching
            query_words = query.lower().split()
            
            # Build fuzzy search conditions for each word
            # Search in title, description, tags, and groups
            sql = '''
                SELECT *,
                    -- Relevance scoring: title matches are weighted highest
                    (CASE 
                        WHEN LOWER(title) = LOWER(?) THEN 100
                        WHEN LOWER(title) LIKE ? THEN 90
                        ELSE 0 
                    END) as title_score,
                    -- Description matches are weighted lower
                    (CASE 
                        WHEN LOWER(description) LIKE ? THEN 50
                        ELSE 0
                    END) as desc_score,
                    -- Tags and groups matches are weighted medium
                    (CASE 
                        WHEN LOWER(tags) LIKE ? OR LOWER(groups) LIKE ? THEN 70
                        ELSE 0
                    END) as tags_score
                FROM datasets
                WHERE (
            '''
            
            # Add conditions for each query word
            conditions = []
            params = []
            
            # Exact and fuzzy title match parameters for scoring
            params.extend([query, f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'])
            
            # Build WHERE conditions for each word
            for word in query_words:
                word_conditions = [
                    'LOWER(title) LIKE ?',
                    'LOWER(description) LIKE ?',
                    'LOWER(tags) LIKE ?',
                    'LOWER(groups) LIKE ?',
                    'LOWER(organization) LIKE ?'
                ]
                conditions.append(f"({' OR '.join(word_conditions)})")
                # Add parameter for each condition
                params.extend([f'%{word}%'] * 5)
            
            sql += ' AND '.join(conditions) + ')'

            if source_id:
                sql += ' AND source_id = ?'
                params.append(source_id)

            # Order by relevance score (sum of all scores), then by title
            sql += ' ORDER BY (title_score + desc_score + tags_score) DESC, title LIMIT ?'
            params.append(limit)

            cursor.execute(sql, params)

            datasets = []
            for row in cursor.fetchall():
                datasets.append(self._row_to_dataset(row))
            return datasets

    def get_dataset_categories(self, source_id: str = None) -> Dict[str, List[str]]:
        """
        Get all unique categories (groups and common tags) from datasets.
        Returns a dict mapping category names to dataset IDs.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            sql = 'SELECT id, groups, tags FROM datasets WHERE 1=1'
            params = []
            
            if source_id:
                sql += ' AND source_id = ?'
                params.append(source_id)
            
            cursor.execute(sql, params)
            
            categories = {}
            
            for row in cursor.fetchall():
                dataset_id = row['id']
                groups = json.loads(row['groups']) if row['groups'] else []
                tags = json.loads(row['tags']) if row['tags'] else []
                
                # Add groups as categories
                for group in groups:
                    if group not in categories:
                        categories[group] = []
                    categories[group].append(dataset_id)
                
                # Add common/meaningful tags as categories
                for tag in tags:
                    # Only include meaningful tags (not too generic)
                    if len(tag) > 3 and tag.lower() not in ['data', 'open', 'stadt']:
                        if tag not in categories:
                            categories[tag] = []
                        categories[tag].append(dataset_id)
            
            return categories

    def get_datasets_by_category(self, source_id: str = None, limit: int = 500) -> Dict[str, Any]:
        """
        Get datasets organized by categories (groups).
        Returns a dict with category information and datasets per category.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            sql = 'SELECT * FROM datasets WHERE 1=1'
            params = []
            
            if source_id:
                sql += ' AND source_id = ?'
                params.append(source_id)
            
            sql += ' ORDER BY title'
            
            if limit:
                sql += ' LIMIT ?'
                params.append(limit)
            
            cursor.execute(sql, params)
            
            # Organize by groups/categories
            categories = {}
            uncategorized = []
            
            for row in cursor.fetchall():
                dataset = self._row_to_dataset(row)
                groups = dataset.groups if dataset.groups else []
                
                if not groups:
                    uncategorized.append(dataset)
                else:
                    for group in groups:
                        if group not in categories:
                            categories[group] = []
                        categories[group].append(dataset)
            
            # Build result
            result = {
                'categories': {}
            }
            
            # Add categorized datasets
            for cat_name, datasets in sorted(categories.items()):
                result['categories'][cat_name] = {
                    'name': cat_name,
                    'count': len(datasets),
                    'datasets': [d.to_dict() for d in datasets]
                }
            
            # Add uncategorized if any
            if uncategorized:
                result['categories']['Uncategorized'] = {
                    'name': 'Uncategorized',
                    'count': len(uncategorized),
                    'datasets': [d.to_dict() for d in uncategorized]
                }
            
            result['total_categories'] = len(result['categories'])
            result['total_datasets'] = sum(cat['count'] for cat in result['categories'].values())
            
            return result

    def _row_to_dataset(self, row: sqlite3.Row) -> Dataset:
        resources_data = json.loads(row['resources']) if row['resources'] else []
        resources = [DatasetResource(**r) for r in resources_data]

        return Dataset(
            id=row['id'],
            source_id=row['source_id'],
            external_id=row['external_id'],
            title=row['title'],
            description=row['description'],
            resources=resources,
            tags=json.loads(row['tags']) if row['tags'] else [],
            groups=json.loads(row['groups']) if row['groups'] else [],
            organization=row['organization'],
            license=row['license'],
            has_geometry=bool(row['has_geometry']),
            geometry_types=json.loads(row['geometry_types']) if row['geometry_types'] else [],
            is_district_specific=bool(row['is_district_specific']),
            district_column=row['district_column'],
            feature_count=row['feature_count'],
            last_modified=datetime.fromisoformat(row['last_modified']) if row['last_modified'] else None,
            last_synced=datetime.fromisoformat(row['last_synced']) if row['last_synced'] else None,
            sync_status=row['sync_status'],
            sync_error=row['sync_error'],
            metadata=json.loads(row['metadata']) if row['metadata'] else {},
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.utcnow(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else datetime.utcnow()
        )

    # =========================================================================
    # Feature Operations
    # =========================================================================

    def upsert_features_batch(self, features: List[Feature]) -> int:
        """Batch insert features, returns count inserted"""
        if not features:
            return 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT OR REPLACE INTO features
                (id, dataset_id, source_id, geometry, geometry_type, properties,
                 district_id, centroid_lat, centroid_lon, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (
                    f.id, f.dataset_id, f.source_id,
                    json.dumps(f.geometry) if f.geometry else None,
                    f.geometry_type,
                    json.dumps(f.properties) if f.properties else None,
                    f.district_id, f.centroid_lat, f.centroid_lon,
                    f.created_at.isoformat()
                ) for f in features
            ])
            return len(features)

    def delete_features_for_dataset(self, dataset_id: str) -> int:
        """Delete all features for a dataset"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM features WHERE dataset_id = ?', (dataset_id,))
            return cursor.rowcount

    def get_features(self, dataset_id: str = None, district_id: str = None,
                     source_id: str = None, limit: int = 1000, offset: int = 0) -> List[Feature]:
        """Get features with optional filters"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = 'SELECT * FROM features WHERE 1=1'
            params = []

            if dataset_id:
                query += ' AND dataset_id = ?'
                params.append(dataset_id)
            if district_id:
                query += ' AND district_id = ?'
                params.append(district_id)
            if source_id:
                query += ' AND source_id = ?'
                params.append(source_id)

            query += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)

            features = []
            for row in cursor.fetchall():
                features.append(self._row_to_feature(row))
            return features

    def get_features_near(self, lat: float, lon: float, radius_km: float = 1.0,
                          dataset_id: str = None, limit: int = 100) -> List[Tuple[Feature, float]]:
        """Get features near a point with distance (uses Haversine approximation)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Approximate degree distance for bounding box
            lat_range = radius_km / 111.0  # ~111km per degree latitude
            lon_range = radius_km / (111.0 * abs(cos(radians(lat))))

            query = '''
                SELECT *,
                    (6371 * acos(
                        cos(radians(?)) * cos(radians(centroid_lat)) *
                        cos(radians(centroid_lon) - radians(?)) +
                        sin(radians(?)) * sin(radians(centroid_lat))
                    )) AS distance_km
                FROM features
                WHERE centroid_lat IS NOT NULL
                    AND centroid_lon IS NOT NULL
                    AND centroid_lat BETWEEN ? AND ?
                    AND centroid_lon BETWEEN ? AND ?
            '''
            params = [lat, lon, lat,
                      lat - lat_range, lat + lat_range,
                      lon - lon_range, lon + lon_range]

            if dataset_id:
                query += ' AND dataset_id = ?'
                params.append(dataset_id)

            query += ' HAVING distance_km <= ? ORDER BY distance_km LIMIT ?'
            params.extend([radius_km, limit])

            try:
                cursor.execute(query, params)
                results = []
                for row in cursor.fetchall():
                    feature = self._row_to_feature(row)
                    distance = row['distance_km']
                    results.append((feature, distance))
                return results
            except sqlite3.OperationalError:
                # Fallback without advanced SQL functions
                return self._get_features_near_fallback(lat, lon, radius_km, dataset_id, limit)

    def _get_features_near_fallback(self, lat: float, lon: float, radius_km: float,
                                     dataset_id: str, limit: int) -> List[Tuple[Feature, float]]:
        """Fallback for features near without advanced SQL"""
        from math import radians, sin, cos, sqrt, atan2

        def haversine(lat1, lon1, lat2, lon2):
            R = 6371
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
            return R * 2 * atan2(sqrt(a), sqrt(1-a))

        features = self.get_features(dataset_id=dataset_id, limit=10000)
        results = []
        for f in features:
            if f.centroid_lat and f.centroid_lon:
                dist = haversine(lat, lon, f.centroid_lat, f.centroid_lon)
                if dist <= radius_km:
                    results.append((f, dist))

        results.sort(key=lambda x: x[1])
        return results[:limit]

    def get_features_geojson(self, dataset_id: str = None, district_id: str = None,
                              limit: int = 1000) -> Dict[str, Any]:
        """Get features as GeoJSON FeatureCollection"""
        features = self.get_features(dataset_id=dataset_id, district_id=district_id, limit=limit)
        return {
            'type': 'FeatureCollection',
            'features': [f.to_geojson_feature() for f in features]
        }

    def _row_to_feature(self, row: sqlite3.Row) -> Feature:
        return Feature(
            id=row['id'],
            dataset_id=row['dataset_id'],
            source_id=row['source_id'],
            geometry=json.loads(row['geometry']) if row['geometry'] else None,
            geometry_type=row['geometry_type'],
            properties=json.loads(row['properties']) if row['properties'] else {},
            district_id=row['district_id'],
            centroid_lat=row['centroid_lat'],
            centroid_lon=row['centroid_lon'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.utcnow()
        )

    # =========================================================================
    # Sync Status Operations
    # =========================================================================

    def update_sync_status(self, status: SyncStatus) -> None:
        """Update sync status for a source"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO sync_status
                (source_id, total_datasets, synced_datasets, failed_datasets, total_features,
                 started_at, completed_at, status, current_dataset, errors)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                status.source_id,
                status.total_datasets,
                status.synced_datasets,
                status.failed_datasets,
                status.total_features,
                status.started_at.isoformat() if status.started_at else None,
                status.completed_at.isoformat() if status.completed_at else None,
                status.status,
                status.current_dataset,
                json.dumps(status.errors)
            ))

    def get_sync_status(self, source_id: str) -> Optional[SyncStatus]:
        """Get sync status for a source"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM sync_status WHERE source_id = ?', (source_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return SyncStatus(
                source_id=row['source_id'],
                total_datasets=row['total_datasets'],
                synced_datasets=row['synced_datasets'],
                failed_datasets=row['failed_datasets'],
                total_features=row['total_features'],
                started_at=datetime.fromisoformat(row['started_at']) if row['started_at'] else None,
                completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
                status=row['status'],
                current_dataset=row['current_dataset'],
                errors=json.loads(row['errors']) if row['errors'] else []
            )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self, source_id: str = None) -> Dict[str, Any]:
        """Get database statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            stats = {}

            # Source-specific or global
            source_filter = ' WHERE source_id = ?' if source_id else ''
            source_params = [source_id] if source_id else []

            cursor.execute(f'SELECT COUNT(*) FROM datasets{source_filter}', source_params)
            stats['total_datasets'] = cursor.fetchone()[0]

            if source_id:
                cursor.execute('SELECT COUNT(*) FROM datasets WHERE source_id = ? AND has_geometry = 1', source_params)
            else:
                cursor.execute('SELECT COUNT(*) FROM datasets WHERE has_geometry = 1')
            stats['geo_datasets'] = cursor.fetchone()[0]

            cursor.execute(f'SELECT COUNT(*) FROM features{source_filter}', source_params)
            stats['total_features'] = cursor.fetchone()[0]

            cursor.execute(f'SELECT COUNT(*) FROM districts{source_filter}', source_params)
            stats['total_districts'] = cursor.fetchone()[0]

            if not source_id:
                cursor.execute('SELECT COUNT(*) FROM data_sources WHERE enabled = 1')
                stats['active_sources'] = cursor.fetchone()[0]

            return stats


# Helper function
def cos(x):
    import math
    return math.cos(x)

def radians(x):
    import math
    return math.radians(x)
