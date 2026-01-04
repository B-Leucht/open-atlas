"""
Data Models for Open Atlas
Designed to support multiple data sources (cities, regions, etc.)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import json


def _to_iso(val: Union[datetime, str, None]) -> Optional[str]:
    """Convert datetime or string to ISO format string"""
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return val.isoformat()


class DataSourceType(Enum):
    """Types of open data sources"""
    CKAN = "ckan"
    SOCRATA = "socrata"
    ARCGIS = "arcgis"
    CUSTOM = "custom"


class GeometryType(Enum):
    """GeoJSON geometry types"""
    POINT = "Point"
    LINESTRING = "LineString"
    POLYGON = "Polygon"
    MULTIPOINT = "MultiPoint"
    MULTILINESTRING = "MultiLineString"
    MULTIPOLYGON = "MultiPolygon"
    GEOMETRYCOLLECTION = "GeometryCollection"


@dataclass
class DataSource:
    """
    Represents an open data source (e.g., a city's open data portal)
    Extensible to support multiple cities/regions
    """
    id: str
    name: str
    display_name: str
    api_base_url: str
    source_type: DataSourceType
    default_crs: str = "EPSG:4326"
    bounds: Optional[Dict[str, float]] = None  # {min_lat, max_lat, min_lon, max_lon}
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_sync: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'api_base_url': self.api_base_url,
            'source_type': self.source_type.value,
            'default_crs': self.default_crs,
            'bounds': self.bounds,
            'config': self.config,
            'enabled': self.enabled,
            'last_sync': _to_iso(self.last_sync)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DataSource':
        return cls(
            id=data['id'],
            name=data['name'],
            display_name=data['display_name'],
            api_base_url=data['api_base_url'],
            source_type=DataSourceType(data['source_type']),
            default_crs=data.get('default_crs', 'EPSG:4326'),
            bounds=data.get('bounds'),
            config=data.get('config', {}),
            enabled=data.get('enabled', True),
            last_sync=datetime.fromisoformat(data['last_sync']) if data.get('last_sync') else None
        )


# Pre-configured data sources
MUNICH_DATA_SOURCE = DataSource(
    id="munich",
    name="opendata_muenchen",
    display_name="Open Data M\u00fcnchen",
    api_base_url="https://opendata.muenchen.de/api/3/action",
    source_type=DataSourceType.CKAN,
    default_crs="EPSG:25832",
    bounds={
        'min_lat': 47.9,
        'max_lat': 48.3,
        'min_lon': 11.2,
        'max_lon': 11.9
    },
    config={
        'district_dataset_id': '906f9c9b-5416-4168-86fe-44aa7c2ac486',
        'district_wfs_url': 'https://geoportal.muenchen.de/geoserver/gsm_wfs/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=gsm_wfs:vablock_stadtbezirke_opendata&outputFormat=application/json'
    }
)


@dataclass
class District:
    """
    Represents an administrative district within a data source
    """
    id: str
    source_id: str  # Reference to DataSource
    number: str  # Official district number (e.g., "04")
    name: str
    geometry: Optional[Dict[str, Any]] = None  # GeoJSON geometry
    centroid_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    area_sqm: Optional[float] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'source_id': self.source_id,
            'number': self.number,
            'name': self.name,
            'geometry': self.geometry,
            'centroid_lat': self.centroid_lat,
            'centroid_lon': self.centroid_lon,
            'area_sqm': self.area_sqm,
            'properties': self.properties,
            'created_at': _to_iso(self.created_at),
            'updated_at': _to_iso(self.updated_at)
        }

    def to_geojson_feature(self) -> Dict[str, Any]:
        """Convert to GeoJSON Feature"""
        return {
            'type': 'Feature',
            'id': self.id,
            'geometry': self.geometry,
            'properties': {
                'district_id': self.id,
                'district_number': self.number,
                'district_name': self.name,
                'area_sqm': self.area_sqm,
                **self.properties
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'District':
        return cls(
            id=data['id'],
            source_id=data['source_id'],
            number=data['number'],
            name=data['name'],
            geometry=data.get('geometry'),
            centroid_lat=data.get('centroid_lat'),
            centroid_lon=data.get('centroid_lon'),
            area_sqm=data.get('area_sqm'),
            properties=data.get('properties', {}),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else datetime.utcnow()
        )


@dataclass
class DatasetResource:
    """
    Represents a single resource/file within a dataset
    """
    id: str
    name: str
    url: str
    format: str
    size: Optional[int] = None
    last_modified: Optional[datetime] = None
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'format': self.format,
            'size': self.size,
            'last_modified': _to_iso(self.last_modified),
            'description': self.description
        }


@dataclass
class Dataset:
    """
    Represents a dataset from an open data source
    """
    id: str
    source_id: str  # Reference to DataSource
    external_id: str  # ID in the source system (e.g., CKAN package ID)
    title: str
    description: Optional[str] = None
    resources: List[DatasetResource] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    organization: Optional[str] = None
    license: Optional[str] = None
    has_geometry: bool = False
    geometry_types: List[str] = field(default_factory=list)
    is_district_specific: bool = False
    district_column: Optional[str] = None
    feature_count: int = 0
    last_modified: Optional[datetime] = None
    last_synced: Optional[datetime] = None
    sync_status: str = "pending"  # pending, syncing, synced, error
    sync_error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'source_id': self.source_id,
            'external_id': self.external_id,
            'title': self.title,
            'description': self.description,
            'resources': [r.to_dict() for r in self.resources],
            'tags': self.tags,
            'groups': self.groups,
            'organization': self.organization,
            'license': self.license,
            'has_geometry': self.has_geometry,
            'geometry_types': self.geometry_types,
            'is_district_specific': self.is_district_specific,
            'district_column': self.district_column,
            'feature_count': self.feature_count,
            'last_modified': _to_iso(self.last_modified),
            'last_synced': _to_iso(self.last_synced),
            'sync_status': self.sync_status,
            'sync_error': self.sync_error,
            'metadata': self.metadata,
            'created_at': _to_iso(self.created_at),
            'updated_at': _to_iso(self.updated_at)
        }

    def get_best_resource(self, format_priority: List[str] = None) -> Optional[DatasetResource]:
        """Get the best resource based on format priority"""
        if format_priority is None:
            format_priority = ['geojson', 'wfs', 'json', 'csv', 'gml', 'shapefile', 'shape']

        for fmt in format_priority:
            for resource in self.resources:
                if resource.format.lower() == fmt.lower():
                    return resource
        return self.resources[0] if self.resources else None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Dataset':
        resources = [
            DatasetResource(**r) if isinstance(r, dict) else r
            for r in data.get('resources', [])
        ]
        return cls(
            id=data['id'],
            source_id=data['source_id'],
            external_id=data['external_id'],
            title=data['title'],
            description=data.get('description'),
            resources=resources,
            tags=data.get('tags', []),
            groups=data.get('groups', []),
            organization=data.get('organization'),
            license=data.get('license'),
            has_geometry=data.get('has_geometry', False),
            geometry_types=data.get('geometry_types', []),
            is_district_specific=data.get('is_district_specific', False),
            district_column=data.get('district_column'),
            feature_count=data.get('feature_count', 0),
            last_modified=datetime.fromisoformat(data['last_modified']) if data.get('last_modified') else None,
            last_synced=datetime.fromisoformat(data['last_synced']) if data.get('last_synced') else None,
            sync_status=data.get('sync_status', 'pending'),
            sync_error=data.get('sync_error'),
            metadata=data.get('metadata', {}),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else datetime.utcnow()
        )


@dataclass
class Feature:
    """
    Represents a single geographic feature from a dataset
    """
    id: str
    dataset_id: str
    source_id: str
    geometry: Optional[Dict[str, Any]] = None
    geometry_type: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    district_id: Optional[str] = None  # Linked district (if applicable)
    centroid_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'dataset_id': self.dataset_id,
            'source_id': self.source_id,
            'geometry': self.geometry,
            'geometry_type': self.geometry_type,
            'properties': self.properties,
            'district_id': self.district_id,
            'centroid_lat': self.centroid_lat,
            'centroid_lon': self.centroid_lon,
            'created_at': _to_iso(self.created_at)
        }

    def to_geojson_feature(self) -> Dict[str, Any]:
        """Convert to GeoJSON Feature"""
        return {
            'type': 'Feature',
            'id': self.id,
            'geometry': self.geometry,
            'properties': {
                'feature_id': self.id,
                'dataset_id': self.dataset_id,
                'district_id': self.district_id,
                **self.properties
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Feature':
        return cls(
            id=data['id'],
            dataset_id=data['dataset_id'],
            source_id=data['source_id'],
            geometry=data.get('geometry'),
            geometry_type=data.get('geometry_type'),
            properties=data.get('properties', {}),
            district_id=data.get('district_id'),
            centroid_lat=data.get('centroid_lat'),
            centroid_lon=data.get('centroid_lon'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.utcnow()
        )

    @classmethod
    def from_geojson(cls, geojson_feature: Dict[str, Any], dataset_id: str, source_id: str, feature_id: str = None) -> 'Feature':
        """Create Feature from GeoJSON feature dict"""
        import uuid

        geometry = geojson_feature.get('geometry')
        properties = geojson_feature.get('properties', {})

        # Calculate centroid for point geometries
        centroid_lat = None
        centroid_lon = None
        geometry_type = None

        if geometry:
            geometry_type = geometry.get('type')
            if geometry_type == 'Point':
                coords = geometry.get('coordinates', [])
                if len(coords) >= 2:
                    centroid_lon, centroid_lat = coords[0], coords[1]
            elif geometry_type in ['Polygon', 'MultiPolygon']:
                # Simple centroid approximation (first coordinate)
                coords = geometry.get('coordinates', [])
                if coords:
                    if geometry_type == 'Polygon' and coords[0]:
                        # Average of polygon exterior ring
                        ring = coords[0]
                        if ring:
                            centroid_lon = sum(c[0] for c in ring) / len(ring)
                            centroid_lat = sum(c[1] for c in ring) / len(ring)

        return cls(
            id=feature_id or str(uuid.uuid4()),
            dataset_id=dataset_id,
            source_id=source_id,
            geometry=geometry,
            geometry_type=geometry_type,
            properties=properties,
            centroid_lat=centroid_lat,
            centroid_lon=centroid_lon
        )


@dataclass
class SyncStatus:
    """Track synchronization status for a data source"""
    source_id: str
    total_datasets: int = 0
    synced_datasets: int = 0
    failed_datasets: int = 0
    total_features: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "idle"  # idle, running, completed, failed
    current_dataset: Optional[str] = None
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'source_id': self.source_id,
            'total_datasets': self.total_datasets,
            'synced_datasets': self.synced_datasets,
            'failed_datasets': self.failed_datasets,
            'total_features': self.total_features,
            'started_at': _to_iso(self.started_at),
            'completed_at': _to_iso(self.completed_at),
            'status': self.status,
            'current_dataset': self.current_dataset,
            'errors': self.errors
        }
