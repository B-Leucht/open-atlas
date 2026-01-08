"""
Data Synchronization Pipeline for Open Atlas
Handles fetching, parsing, and storing data from open data sources
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

import requests

from .database import Database
from .districts import DistrictService
from .models import (
    DataSource, Dataset, DatasetResource, Feature, SyncStatus,
    MUNICH_DATA_SOURCE, GOVDATA_DATA_SOURCE, DataSourceType
)
from .parsers import DataParser, ParseResult

logger = logging.getLogger(__name__)

# District indicator columns (found in CSV headers)
DISTRICT_COLUMN_PATTERNS = [
    'sb_nummer', 'stadtbezirk', 'bezirk', 'bezirksnummer', 'district',
    'stadtbezirk_nr', 'bezirks_nr', 'sbz', 'stadtteil',
    'raumbezug'  # Indikatorenatlas uses this format: "01 Altstadt - Lehel"
]

# Dataset name/tag patterns that indicate district-level data
DISTRICT_DATASET_PATTERNS = [
    'indikatorenatlas',  # All Indikatorenatlas datasets are district-level
    'stadtbezirk',
    'bevölkerung',
]


class DataSync:
    """
    Synchronization service for fetching and storing open data.
    Supports incremental and full sync modes.
    """

    def __init__(self, db: Database = None, parser: DataParser = None):
        self.db = db or Database()
        self.parser = parser or DataParser()
        self.district_service = DistrictService(self.db)
        self._progress_callback: Optional[Callable[[str, int, int], None]] = None

    def set_progress_callback(self, callback: Callable[[str, int, int], None]):
        """Set callback for progress updates: callback(message, current, total)"""
        self._progress_callback = callback

    def _report_progress(self, message: str, current: int = 0, total: int = 0):
        """Report progress to callback if set"""
        if self._progress_callback:
            self._progress_callback(message, current, total)
        logger.info(f"{message} ({current}/{total})" if total else message)

    # =========================================================================
    # Full Sync
    # =========================================================================

    def sync_source(self, source: DataSource = None, sync_features: bool = True,
                    max_datasets: int = None, parallel: int = 4) -> SyncStatus:
        """
        Full synchronization of a data source.

        Args:
            source: Data source to sync (defaults to Munich)
            sync_features: Whether to also sync feature data (slower)
            max_datasets: Limit number of datasets to sync (for testing)
            parallel: Number of parallel workers for feature sync

        Returns:
            SyncStatus with results
        """
        source = source or MUNICH_DATA_SOURCE

        status = SyncStatus(
            source_id=source.id,
            status='running',
            started_at=datetime.utcnow()
        )
        self.db.update_sync_status(status)

        try:
            # Step 1: Sync districts
            self._report_progress(f"Syncing districts for {source.display_name}...")
            district_count = self.district_service.ingest_districts(source)
            self._report_progress(f"Synced {district_count} districts")

            # Step 2: Sync dataset metadata
            self._report_progress(f"Fetching dataset catalog...")
            datasets = self._fetch_catalog(source)
            status.total_datasets = len(datasets)

            if max_datasets:
                datasets = datasets[:max_datasets]
                status.total_datasets = len(datasets)

            self._report_progress(f"Found {len(datasets)} datasets")

            # Step 3: Process each dataset
            for i, dataset in enumerate(datasets):
                status.current_dataset = dataset.title
                status.synced_datasets = i
                self.db.update_sync_status(status)
                self._report_progress(f"Processing: {dataset.title}", i + 1, len(datasets))

                try:
                    # Analyze dataset for geo capability
                    self._analyze_dataset(dataset)

                    # Save metadata
                    self.db.upsert_dataset(dataset)

                    # Sync features if requested (for geo datasets or district-specific datasets)
                    if sync_features and (dataset.has_geometry or dataset.is_district_specific):
                        feature_count = self._sync_dataset_features(dataset)
                        dataset.feature_count = feature_count
                        dataset.last_synced = datetime.utcnow()
                        dataset.sync_status = 'synced'
                        self.db.upsert_dataset(dataset)
                        status.total_features += feature_count

                    status.synced_datasets = i + 1

                except Exception as e:
                    logger.error(f"Error syncing dataset {dataset.external_id}: {e}")
                    dataset.sync_status = 'error'
                    dataset.sync_error = str(e)
                    self.db.upsert_dataset(dataset)
                    status.failed_datasets += 1
                    status.errors.append(f"{dataset.title}: {str(e)}")

            # Complete
            status.status = 'completed'
            status.completed_at = datetime.utcnow()
            status.current_dataset = None

            # Update source last sync time
            source.last_sync = datetime.utcnow()
            self.db.upsert_data_source(source)

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            status.status = 'failed'
            status.errors.append(str(e))

        self.db.update_sync_status(status)
        self._report_progress(f"Sync completed: {status.synced_datasets} datasets, {status.total_features} features")

        return status

    def sync_dataset(self, source_id: str, external_id: str) -> Optional[Dataset]:
        """Sync a single dataset by its external ID"""
        source = self.db.get_data_source(source_id)
        if not source:
            logger.error(f"Source not found: {source_id}")
            return None

        # Fetch dataset metadata
        dataset = self._fetch_dataset_metadata(source, external_id)
        if not dataset:
            return None

        # Analyze and sync
        self._analyze_dataset(dataset)
        self.db.upsert_dataset(dataset)

        if dataset.has_geometry:
            feature_count = self._sync_dataset_features(dataset)
            dataset.feature_count = feature_count
            dataset.last_synced = datetime.utcnow()
            dataset.sync_status = 'synced'
            self.db.upsert_dataset(dataset)

        return dataset

    # =========================================================================
    # Catalog Fetching
    # =========================================================================

    def _fetch_catalog(self, source: DataSource) -> List[Dataset]:
        """Fetch all datasets from a source's catalog"""
        if source.source_type == DataSourceType.CKAN:
            datasets = self._fetch_ckan_catalog(source)
            # Apply filtering for GovData source
            if source.id == 'govdata':
                datasets = self._filter_govdata_datasets(datasets, source)
            return datasets
        else:
            logger.warning(f"Unsupported source type: {source.source_type}")
            return []

    def _fetch_ckan_catalog(self, source: DataSource) -> List[Dataset]:
        """Fetch catalog from CKAN API"""
        datasets = []

        # For GovData, use search API to find relevant datasets more efficiently
        if source.id == 'govdata':
            return self._fetch_govdata_search_catalog(source)
        
        # For other sources, use traditional package_list approach
        # Get all package IDs
        list_url = f"{source.api_base_url}/package_list"
        response = requests.get(list_url, timeout=30)
        response.raise_for_status()
        package_ids = response.json().get('result', [])

        self._report_progress(f"Fetching metadata for {len(package_ids)} packages...")

        # Fetch each package
        for i, pkg_id in enumerate(package_ids):
            if i % 50 == 0:
                self._report_progress(f"Fetching package metadata...", i, len(package_ids))

            try:
                dataset = self._fetch_dataset_metadata(source, pkg_id)
                if dataset:
                    datasets.append(dataset)
            except Exception as e:
                logger.warning(f"Error fetching {pkg_id}: {e}")

        return datasets

    def _fetch_govdata_search_catalog(self, source: DataSource) -> List[Dataset]:
        """Fetch GovData catalog using search API for better performance"""
        datasets = []
        location_filters = source.config.get('location_filters', ['munich', 'münchen', 'bayern', 'bavaria'])
        
        # Search for each location term
        all_results = []
        for term in location_filters:
            try:
                search_url = f"{source.api_base_url}/package_search"
                params = {
                    'q': term,
                    'rows': 1000,  # Get up to 1000 results per term
                    'start': 0
                }
                
                response = requests.get(search_url, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                results = data.get('result', {}).get('results', [])
                all_results.extend(results)
                
                self._report_progress(f"Found {len(results)} datasets for term '{term}'")
                
            except Exception as e:
                logger.warning(f"Error searching for '{term}': {e}")
        
        # Remove duplicates by ID
        seen_ids = set()
        unique_results = []
        for result in all_results:
            if result['id'] not in seen_ids:
                seen_ids.add(result['id'])
                unique_results.append(result)
        
        self._report_progress(f"Processing {len(unique_results)} unique datasets...")
        
        # Convert to Dataset objects
        for i, result in enumerate(unique_results):
            try:
                dataset = self._ckan_result_to_dataset(source, result)
                if dataset:
                    datasets.append(dataset)
                    
                if i % 50 == 0:
                    self._report_progress(f"Converting datasets...", i, len(unique_results))
                    
            except Exception as e:
                logger.warning(f"Error converting dataset {result.get('id', 'unknown')}: {e}")
        
        return datasets

    def _ckan_result_to_dataset(self, source: DataSource, result: Dict) -> Optional[Dataset]:
        """Convert CKAN search result to Dataset object"""
        try:
            # Parse resources
            resources = []
            for res in result.get('resources', []):
                resources.append(DatasetResource(
                    id=res.get('id', str(uuid.uuid4())),
                    name=res.get('name', ''),
                    url=res.get('url', ''),
                    format=res.get('format', '').upper(),
                    size=res.get('size'),
                    last_modified=datetime.fromisoformat(res['last_modified']) if res.get('last_modified') else None,
                    description=res.get('description')
                ))

            # Parse tags
            tags = [t.get('name', '') for t in result.get('tags', [])]

            # Parse groups
            groups = [g.get('title', '') for g in result.get('groups', [])]

            # Organization
            org = result.get('organization', {})
            organization = org.get('title') if org else None

            return Dataset(
                id=f"{source.id}_{result['id']}",
                source_id=source.id,
                external_id=result['id'],
                title=result.get('title', ''),
                description=result.get('notes', ''),
                resources=resources,
                tags=tags,
                groups=groups,
                organization=organization,
                license=result.get('license_id'),
                last_modified=datetime.fromisoformat(result['metadata_modified']) if result.get('metadata_modified') else None,
                metadata={
                    'frequency': result.get('frequency'),
                    'temporal_coverage': result.get('temporal_coverage'),
                    'spatial_uri': result.get('spatial_uri')
                }
            )

        except Exception as e:
            logger.error(f"Error converting CKAN result to dataset: {e}")
            return None

    def _filter_govdata_datasets(self, datasets: List[Dataset], source: DataSource) -> List[Dataset]:
        """Filter GovData datasets for Munich/Bayern location and usable formats"""
        location_filters = source.config.get('location_filters', ['munich', 'münchen', 'bayern', 'bavaria'])
        filtered_datasets = []
        
        for dataset in datasets:
            # Check if dataset has usable resources (respect existing file format filtering)
            if not dataset.has_usable_resources():
                continue
                
            # Check location relevance in title, description, tags, and groups
            text_to_check = ' '.join([
                dataset.title.lower(),
                dataset.description.lower() if dataset.description else '',
                ' '.join(dataset.tags).lower(),
                ' '.join(dataset.groups).lower(),
                dataset.organization.lower() if dataset.organization else ''
            ])
            
            # Check if any location filter matches
            location_match = any(filter_term in text_to_check for filter_term in location_filters)
            
            if location_match:
                filtered_datasets.append(dataset)
                logger.debug(f"Included GovData dataset: {dataset.title}")
            else:
                logger.debug(f"Excluded GovData dataset (no location match): {dataset.title}")
        
        logger.info(f"Filtered GovData datasets: {len(filtered_datasets)}/{len(datasets)} remain after location filtering")
        return filtered_datasets

    def _fetch_dataset_metadata(self, source: DataSource, external_id: str) -> Optional[Dataset]:
        """Fetch metadata for a single dataset"""
        if source.source_type == DataSourceType.CKAN:
            return self._fetch_ckan_package(source, external_id)
        return None

    def _fetch_ckan_package(self, source: DataSource, package_id: str) -> Optional[Dataset]:
        """Fetch a CKAN package"""
        try:
            url = f"{source.api_base_url}/package_show"
            response = requests.get(url, params={'id': package_id}, timeout=10)
            response.raise_for_status()

            data = response.json()
            if not data.get('success'):
                return None

            pkg = data['result']

            # Parse resources
            resources = []
            for res in pkg.get('resources', []):
                resources.append(DatasetResource(
                    id=res.get('id', str(uuid.uuid4())),
                    name=res.get('name', ''),
                    url=res.get('url', ''),
                    format=res.get('format', '').upper(),
                    size=res.get('size'),
                    last_modified=datetime.fromisoformat(res['last_modified']) if res.get('last_modified') else None,
                    description=res.get('description')
                ))

            # Parse tags
            tags = [t.get('name', '') for t in pkg.get('tags', [])]

            # Parse groups
            groups = [g.get('title', '') for g in pkg.get('groups', [])]

            # Organization
            org = pkg.get('organization', {})
            organization = org.get('title') if org else None

            return Dataset(
                id=f"{source.id}_{pkg['id']}",
                source_id=source.id,
                external_id=pkg['id'],
                title=pkg.get('title', ''),
                description=pkg.get('notes', ''),
                resources=resources,
                tags=tags,
                groups=groups,
                organization=organization,
                license=pkg.get('license_id'),
                last_modified=datetime.fromisoformat(pkg['metadata_modified']) if pkg.get('metadata_modified') else None,
                metadata={
                    'frequency': pkg.get('frequency'),
                    'temporal_coverage': pkg.get('temporal_coverage'),
                    'spatial_uri': pkg.get('spatial_uri')
                }
            )

        except Exception as e:
            logger.error(f"Error fetching CKAN package {package_id}: {e}")
            return None

    # =========================================================================
    # Dataset Analysis
    # =========================================================================

    def _analyze_dataset(self, dataset: Dataset) -> None:
        """Analyze a dataset to determine geo capability and district specificity"""
        # Check formats for geo capability
        geo_formats = {'geojson', 'wfs', 'wms', 'shapefile', 'shape', 'gml', 'kml', 'gpx'}
        geo_resources = [r for r in dataset.resources if r.format.lower() in geo_formats]

        if geo_resources:
            dataset.has_geometry = True
            dataset.geometry_types = list(set(r.format.lower() for r in geo_resources))

        # Try to detect from best resource
        best_resource = dataset.get_best_resource()
        if best_resource and not dataset.has_geometry:
            try:
                result = self.parser.parse(best_resource.url, best_resource.format)
                if result.success and result.has_geometry:
                    dataset.has_geometry = True
            except:
                pass

        # Check for district-specific patterns in tags/title
        text_to_check = ' '.join([
            dataset.title.lower(),
            dataset.description.lower() if dataset.description else '',
            ' '.join(dataset.tags).lower()
        ])

        # Check both column patterns and dataset patterns
        all_patterns = DISTRICT_COLUMN_PATTERNS + DISTRICT_DATASET_PATTERNS
        for pattern in all_patterns:
            if pattern in text_to_check:
                dataset.is_district_specific = True
                break

    # =========================================================================
    # Feature Sync
    # =========================================================================

    def _sync_dataset_features(self, dataset: Dataset) -> int:
        """Sync features for a dataset"""
        # Skip datasets without usable resources
        if not dataset.has_usable_resources():
            logger.debug(f"Skipping {dataset.title} - no usable resources")
            return 0

        best_resource = dataset.get_best_resource()
        if not best_resource:
            return 0

        if not best_resource.url or not best_resource.url.startswith('http'):
            logger.debug(f"Skipping invalid URL for {dataset.title}")
            return 0

        try:
            # Parse the resource
            result = self.parser.parse(best_resource.url, best_resource.format)
            if not result.success or not result.geojson:
                logger.debug(f"Could not parse {dataset.title}: {result.error}")
                return 0

            geojson_features = result.geojson.get('features', [])
            if not geojson_features:
                return 0

            # Convert to Feature objects
            features = []
            for i, gf in enumerate(geojson_features):
                feature = Feature.from_geojson(
                    gf,
                    dataset_id=dataset.id,
                    source_id=dataset.source_id,
                    feature_id=f"{dataset.id}_f{i}"
                )
                features.append(feature)

            # Assign districts to features (by geometry or by district number property)
            self._assign_districts_to_features(features, dataset.source_id)

            # Delete old features and insert new
            self.db.delete_features_for_dataset(dataset.id)

            # Batch insert
            batch_size = 500
            total_inserted = 0
            for i in range(0, len(features), batch_size):
                batch = features[i:i + batch_size]
                self.db.upsert_features_batch(batch)
                total_inserted += len(batch)

            logger.info(f"Synced {total_inserted} features for {dataset.title}")
            return total_inserted

        except Exception as e:
            logger.error(f"Error syncing features for {dataset.title}: {e}")
            return 0

    def _assign_districts_to_features(self, features: List[Feature], source_id: str) -> None:
        """Assign district IDs to features based on location or district number property"""
        districts = self.district_service.get_districts(source_id)
        if not districts:
            return

        # Build lookup by district number for non-geo features
        district_by_number = {d.number: d for d in districts}

        for feature in features:
            # First, try to assign by _district_number property (for Indikatorenatlas etc.)
            props = feature.properties or {}
            district_num = props.get('_district_number')
            if district_num and district_num in district_by_number:
                feature.district_id = district_by_number[district_num].id
                continue

            # Fall back to spatial assignment for features with geometry
            if not feature.centroid_lat or not feature.centroid_lon:
                continue

            for district in districts:
                if district.geometry and self.district_service._point_in_geometry(
                    feature.centroid_lon, feature.centroid_lat, district.geometry
                ):
                    feature.district_id = district.id
                    break

    # =========================================================================
    # Sync Status
    # =========================================================================

    def get_sync_status(self, source_id: str) -> Optional[SyncStatus]:
        """Get current sync status for a source"""
        return self.db.get_sync_status(source_id)


# =========================================================================
# CLI Entry Points
# =========================================================================

def sync_munich(sync_features: bool = True, max_datasets: int = None) -> SyncStatus:
    """Sync Munich open data"""
    sync = DataSync()
    return sync.sync_source(MUNICH_DATA_SOURCE, sync_features=sync_features, max_datasets=max_datasets)


def sync_munich_metadata_only(max_datasets: int = None) -> SyncStatus:
    """Sync only metadata (faster)"""
    return sync_munich(sync_features=False, max_datasets=max_datasets)


def sync_govdata(sync_features: bool = True, max_datasets: int = None) -> SyncStatus:
    """Sync GovData.de open data"""
    sync = DataSync()
    return sync.sync_source(GOVDATA_DATA_SOURCE, sync_features=sync_features, max_datasets=max_datasets)


def sync_govdata_metadata_only(max_datasets: int = None) -> SyncStatus:
    """Sync only metadata (faster)"""
    return sync_govdata(sync_features=False, max_datasets=max_datasets)


if __name__ == '__main__':
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description='Sync Munich Open Data')
    parser.add_argument('--metadata-only', action='store_true', help='Only sync metadata')
    parser.add_argument('--max-datasets', type=int, help='Limit datasets to sync')
    parser.add_argument('--districts-only', action='store_true', help='Only sync districts')

    args = parser.parse_args()

    if args.districts_only:
        db = Database()
        service = DistrictService(db)
        count = service.ingest_districts(MUNICH_DATA_SOURCE)
        print(f"Synced {count} districts")
    else:
        status = sync_munich(
            sync_features=not args.metadata_only,
            max_datasets=args.max_datasets
        )
        print(f"\nSync completed:")
        print(f"  Status: {status.status}")
        print(f"  Datasets: {status.synced_datasets}/{status.total_datasets}")
        print(f"  Features: {status.total_features}")
        print(f"  Errors: {len(status.errors)}")
