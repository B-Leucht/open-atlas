"""
District Service for Open Atlas
Handles district boundary ingestion and spatial operations
"""

import json
import logging
import uuid
from math import cos, radians
from typing import Any, Dict, List, Optional, Tuple

import requests

from .database import Database
from .models import DataSource, District, MUNICH_DATA_SOURCE
from .parsers import CoordinateTransformer, DataParser

logger = logging.getLogger(__name__)


class DistrictService:
    """
    Service for managing district boundaries and spatial operations.
    Supports multiple data sources with their own district definitions.
    """

    def __init__(self, db: Database = None):
        self.db = db or Database()
        self.parser = DataParser()

    def ingest_districts(self, source: DataSource = None) -> int:
        """
        Ingest district boundaries for a data source.
        Returns number of districts ingested.
        """
        source = source or MUNICH_DATA_SOURCE

        if source.id == 'munich':
            return self._ingest_munich_districts(source)
        else:
            logger.warning(f"No district ingestion handler for source: {source.id}")
            return 0

    def _ingest_munich_districts(self, source: DataSource) -> int:
        """Ingest Munich district boundaries from WFS"""
        wfs_url = source.config.get('district_wfs_url')
        if not wfs_url:
            logger.error("No district WFS URL configured for Munich")
            return 0

        try:
            logger.info(f"Fetching Munich districts from WFS...")
            response = requests.get(wfs_url, timeout=60)
            response.raise_for_status()
            data = response.json()

            features = data.get('features', [])
            logger.info(f"Found {len(features)} district features")

            # Detect CRS
            source_crs = None
            if 'crs' in data:
                crs_props = data.get('crs', {}).get('properties', {})
                source_crs = crs_props.get('name', '')
                logger.info(f"Source CRS: {source_crs}")

            districts = []
            district_by_number = {}  # Track best geometry per district

            def count_points(geom):
                """Count total points in a geometry"""
                if not geom:
                    return 0
                coords = geom.get('coordinates', [])
                if geom.get('type') == 'Polygon':
                    return len(coords[0]) if coords else 0
                elif geom.get('type') == 'MultiPolygon':
                    return sum(len(ring[0]) if ring else 0 for ring in coords)
                return 0

            for feature in features:
                props = feature.get('properties', {})
                geometry = feature.get('geometry')

                # Extract district number and name
                number = props.get('sb_nummer', '').strip()
                name = props.get('name', '').strip()

                if not number or not name:
                    logger.warning(f"Skipping feature with missing number/name: {props}")
                    continue

                # Handle duplicates: keep the geometry with more points
                current_points = count_points(geometry)
                if number in district_by_number:
                    existing = district_by_number[number]
                    existing_points = count_points(existing['geometry'])
                    if current_points <= existing_points:
                        logger.debug(f"Skipping smaller duplicate for {number}: {current_points} vs {existing_points} points")
                        continue
                    logger.debug(f"Replacing {number} with larger geometry: {current_points} vs {existing_points} points")

                district_by_number[number] = {'props': props, 'geometry': geometry, 'name': name}

            # Build district objects from the best geometries
            for number, data in district_by_number.items():
                props = data['props']
                geometry = data['geometry']
                name = data['name']

                # Transform geometry coordinates
                if geometry:
                    geometry = CoordinateTransformer.transform_geometry(geometry, source_crs)

                # Calculate centroid
                centroid_lat, centroid_lon = self._calculate_centroid(geometry)

                # Get area
                area_sqm = props.get('flaeche_qm')

                district = District(
                    id=f"{source.id}_district_{number}",
                    source_id=source.id,
                    number=number,
                    name=name,
                    geometry=geometry,
                    centroid_lat=centroid_lat,
                    centroid_lon=centroid_lon,
                    area_sqm=float(area_sqm) if area_sqm else None,
                    properties={
                        'objectid': props.get('objectid'),
                        'x': props.get('x'),
                        'y': props.get('y')
                    }
                )
                districts.append(district)

            # Save to database
            self.db.upsert_districts_batch(districts)
            logger.info(f"Saved {len(districts)} Munich districts to database")

            return len(districts)

        except Exception as e:
            logger.error(f"Error ingesting Munich districts: {e}")
            raise

    def _calculate_centroid(self, geometry: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """Calculate centroid of a geometry"""
        if not geometry:
            return None, None

        geom_type = geometry.get('type')
        coords = geometry.get('coordinates', [])

        if geom_type == 'Point':
            if len(coords) >= 2:
                return coords[1], coords[0]  # lat, lon

        elif geom_type == 'Polygon':
            if coords and coords[0]:
                ring = coords[0]
                lon = sum(c[0] for c in ring) / len(ring)
                lat = sum(c[1] for c in ring) / len(ring)
                return lat, lon

        elif geom_type == 'MultiPolygon':
            all_coords = []
            for polygon in coords:
                if polygon and polygon[0]:
                    all_coords.extend(polygon[0])
            if all_coords:
                lon = sum(c[0] for c in all_coords) / len(all_coords)
                lat = sum(c[1] for c in all_coords) / len(all_coords)
                return lat, lon

        return None, None

    def get_districts(self, source_id: str = None) -> List[District]:
        """Get all districts for a source"""
        return self.db.get_districts(source_id)

    def get_district(self, district_id: str) -> Optional[District]:
        """Get a specific district"""
        return self.db.get_district(district_id)

    def get_district_by_number(self, source_id: str, number: str) -> Optional[District]:
        """Get district by number"""
        return self.db.get_district_by_number(source_id, number)

    def get_districts_geojson(self, source_id: str = None) -> Dict[str, Any]:
        """Get districts as GeoJSON FeatureCollection"""
        return self.db.get_districts_geojson(source_id)

    def find_district_for_point(self, lat: float, lon: float, source_id: str = None) -> Optional[District]:
        """
        Find which district contains a given point.
        Uses simple point-in-polygon test.
        """
        districts = self.get_districts(source_id)

        for district in districts:
            if district.geometry and self._point_in_geometry(lon, lat, district.geometry):
                return district

        return None

    def _point_in_geometry(self, lon: float, lat: float, geometry: Dict[str, Any]) -> bool:
        """Check if a point is inside a geometry (simple ray casting)"""
        geom_type = geometry.get('type')
        coords = geometry.get('coordinates', [])

        if geom_type == 'Polygon':
            return self._point_in_polygon(lon, lat, coords[0]) if coords else False

        elif geom_type == 'MultiPolygon':
            for polygon in coords:
                if polygon and self._point_in_polygon(lon, lat, polygon[0]):
                    return True
            return False

        return False

    def _point_in_polygon(self, x: float, y: float, polygon: List[List[float]]) -> bool:
        """Ray casting algorithm for point-in-polygon test"""
        n = len(polygon)
        inside = False

        j = n - 1
        for i in range(n):
            xi, yi = polygon[i][0], polygon[i][1]
            xj, yj = polygon[j][0], polygon[j][1]

            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside

            j = i

        return inside

    def assign_district_to_features(self, features: List[Dict[str, Any]],
                                     source_id: str = None) -> List[Dict[str, Any]]:
        """
        Assign district IDs to features based on their coordinates.
        Modifies features in place and returns them.
        """
        districts = self.get_districts(source_id)
        if not districts:
            return features

        for feature in features:
            geometry = feature.get('geometry')
            if not geometry:
                continue

            # Get point for geometry
            lat, lon = self._get_feature_point(geometry)
            if lat is None or lon is None:
                continue

            # Find containing district
            for district in districts:
                if district.geometry and self._point_in_geometry(lon, lat, district.geometry):
                    feature['properties'] = feature.get('properties', {})
                    feature['properties']['district_id'] = district.id
                    feature['properties']['district_number'] = district.number
                    feature['properties']['district_name'] = district.name
                    break

        return features

    def _get_feature_point(self, geometry: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """Get a representative point for a geometry (for district lookup)"""
        return self._calculate_centroid(geometry)

    def get_district_statistics(self, source_id: str = None) -> Dict[str, Any]:
        """Get statistics about districts"""
        districts = self.get_districts(source_id)

        stats = {
            'count': len(districts),
            'total_area_sqkm': 0,
            'districts': []
        }

        for d in districts:
            area_sqkm = d.area_sqm / 1_000_000 if d.area_sqm else 0
            stats['total_area_sqkm'] += area_sqkm
            stats['districts'].append({
                'number': d.number,
                'name': d.name,
                'area_sqkm': round(area_sqkm, 2)
            })

        stats['total_area_sqkm'] = round(stats['total_area_sqkm'], 2)
        return stats


# Convenience functions for direct use
def ingest_munich_districts(db: Database = None) -> int:
    """Ingest Munich district boundaries"""
    service = DistrictService(db)
    return service.ingest_districts(MUNICH_DATA_SOURCE)


def get_munich_districts_geojson(db: Database = None) -> Dict[str, Any]:
    """Get Munich districts as GeoJSON"""
    service = DistrictService(db)
    return service.get_districts_geojson('munich')
