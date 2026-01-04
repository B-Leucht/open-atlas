"""
Unified Data Parsers for Munich Open Data
Supports: CSV, GeoJSON, JSON, WFS, WMS, Shapefile, XML, GML
All formats are converted to a unified GeoJSON FeatureCollection
"""

import csv
import io
import json
import logging
import tempfile
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)


def parse_district_number(value: str) -> Optional[str]:
    """
    Parse district number from various formats.

    Examples:
    - "01 Altstadt - Lehel" -> "01" (Indikatorenatlas Raumbezug format)
    - "Stadt München" -> None (city-wide, not a district)
    - "01" -> "01"
    - "1" -> "01"
    - "Altstadt-Lehel" -> None (name only, can't extract number)
    """
    if not value:
        return None

    val = str(value).strip()

    # Skip city-wide entries
    if val.lower().startswith('stadt') or val.lower() == 'münchen':
        return None

    # Try to extract leading number (handles "01 Altstadt - Lehel")
    parts = val.split(' ', 1)
    if parts:
        first = parts[0].strip()
        # Check if it's a number (possibly with leading zero)
        if first.isdigit():
            return first.zfill(2)

    # Check if entire value is a number
    if val.isdigit():
        return val.zfill(2)

    return None


def parse_german_number(value: str) -> Optional[float]:
    """
    Parse a number that may be in German format.
    German format uses:
    - dot (.) as thousands separator
    - comma (,) as decimal separator

    Examples:
    - "1.234,56" -> 1234.56
    - "123,45" -> 123.45
    - "0,2" -> 0.2
    - "1234" -> 1234.0
    - "1.234" -> 1234.0 (ambiguous, treated as thousands separator)
    """
    if not value:
        return None

    val_str = str(value).strip()
    if not val_str:
        return None

    try:
        # If both dot and comma present, it's German format
        if '.' in val_str and ',' in val_str:
            # Remove thousands separator (dots), replace decimal comma with dot
            val_str = val_str.replace('.', '').replace(',', '.')
        elif ',' in val_str:
            # Only comma - it's the decimal separator
            val_str = val_str.replace(',', '.')
        # If only dot, it could be:
        # - US decimal (1234.56)
        # - German thousands (1.234)
        # We assume US decimal for consistency with coordinates

        return float(val_str)
    except (ValueError, TypeError):
        return None


# Munich area coordinate bounds (WGS84)
MUNICH_BOUNDS = {
    'min_lat': 47.9,
    'max_lat': 48.3,
    'min_lon': 11.2,
    'max_lon': 11.9
}

# EPSG:25832 (UTM Zone 32N) approximate bounds for Munich
# Extended bounds to catch edge cases
UTM32N_MUNICH_BOUNDS = {
    'min_x': 670000,
    'max_x': 720000,
    'min_y': 5310000,
    'max_y': 5360000
}


@dataclass
class ParseResult:
    """Result from parsing a data source"""
    success: bool
    geojson: Optional[Dict[str, Any]]
    feature_count: int
    has_geometry: bool
    error: Optional[str] = None
    source_crs: Optional[str] = None
    format_detected: Optional[str] = None


class CoordinateTransformer:
    """Transform coordinates between coordinate reference systems"""

    @staticmethod
    def is_utm32n(x: float, y: float) -> bool:
        """Check if coordinates appear to be EPSG:25832 (UTM Zone 32N)"""
        return (UTM32N_MUNICH_BOUNDS['min_x'] <= x <= UTM32N_MUNICH_BOUNDS['max_x'] and
                UTM32N_MUNICH_BOUNDS['min_y'] <= y <= UTM32N_MUNICH_BOUNDS['max_y'])

    @staticmethod
    def is_wgs84(lon: float, lat: float) -> bool:
        """Check if coordinates appear to be WGS84"""
        return (MUNICH_BOUNDS['min_lon'] <= lon <= MUNICH_BOUNDS['max_lon'] and
                MUNICH_BOUNDS['min_lat'] <= lat <= MUNICH_BOUNDS['max_lat'])

    @staticmethod
    def utm32n_to_wgs84(x: float, y: float) -> Tuple[float, float]:
        """Convert EPSG:25832 (UTM Zone 32N) to WGS84 (EPSG:4326)"""
        try:
            import pyproj
            transformer = pyproj.Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
            lon, lat = transformer.transform(x, y)
            return lon, lat
        except ImportError:
            # Fallback: approximate conversion for Munich area
            # This is a rough approximation - pyproj should be installed for accuracy
            lon = 11.5 + (x - 691000) / 70000
            lat = 48.1 + (y - 5334000) / 111000
            return lon, lat

    @staticmethod
    def transform_coordinates(coords: Any, source_crs: str = None) -> Any:
        """Recursively transform coordinates in a geometry"""
        if isinstance(coords, (list, tuple)):
            if len(coords) >= 2 and isinstance(coords[0], (int, float)):
                x, y = coords[0], coords[1]
                if CoordinateTransformer.is_utm32n(x, y):
                    lon, lat = CoordinateTransformer.utm32n_to_wgs84(x, y)
                    return [lon, lat] if len(coords) == 2 else [lon, lat] + list(coords[2:])
                return coords
            return [CoordinateTransformer.transform_coordinates(c, source_crs) for c in coords]
        return coords

    @staticmethod
    def transform_geometry(geometry: Dict[str, Any], source_crs: str = None) -> Dict[str, Any]:
        """Transform all coordinates in a GeoJSON geometry"""
        if not geometry or 'coordinates' not in geometry:
            return geometry

        return {
            'type': geometry['type'],
            'coordinates': CoordinateTransformer.transform_coordinates(
                geometry['coordinates'],
                source_crs
            )
        }


class BaseParser(ABC):
    """Base class for all data parsers"""

    @abstractmethod
    def parse(self, source: str, **kwargs) -> ParseResult:
        """Parse data from source (URL or content)"""
        pass

    @abstractmethod
    def can_parse(self, source: str, content_type: str = None) -> bool:
        """Check if this parser can handle the given source"""
        pass

    def _fetch_url(self, url: str, timeout: int = 60) -> Tuple[str, str]:
        """Fetch content from URL, return (content, content_type)"""
        if not url or not url.startswith('http'):
            raise ValueError(f"Invalid URL: {url}")
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '')
        # Check if we got an error page instead of data
        if 'text/html' in content_type.lower() and not url.endswith('.html'):
            # Might be an error page, check content
            if '<html' in response.text[:500].lower():
                raise ValueError("Received HTML instead of expected data format")
        return response.text, content_type

    def _fetch_binary(self, url: str, timeout: int = 60) -> Tuple[bytes, str]:
        """Fetch binary content from URL"""
        if not url or not url.startswith('http'):
            raise ValueError(f"Invalid URL: {url}")
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '')
        return response.content, content_type


class CSVParser(BaseParser):
    """Parser for CSV files with auto-detection of coordinate columns"""

    LAT_PATTERNS = ['lat', 'latitude', 'breitengrad', 'y', 'northing', 'y_koordinate', 'y-koordinate']
    LON_PATTERNS = ['lon', 'lng', 'longitude', 'laengengrad', 'längengrad', 'x', 'easting',
                    'x_koordinate', 'x-koordinate']
    DISTRICT_PATTERNS = ['sb_nummer', 'stadtbezirk', 'bezirk', 'bezirksnummer', 'district',
                         'raumbezug']  # Indikatorenatlas format: "01 Altstadt - Lehel"

    def can_parse(self, source: str, content_type: str = None) -> bool:
        if content_type and 'csv' in content_type.lower():
            return True
        return source.lower().endswith('.csv') or 'outputformat=csv' in source.lower()

    def _fix_encoding(self, content: str) -> str:
        """Fix common encoding issues with German text"""
        # If content has mojibake (UTF-8 decoded as Latin-1), try to fix it
        try:
            # Check for common mojibake patterns
            if 'Ã¶' in content or 'Ã¤' in content or 'Ã¼' in content or 'ÃŸ' in content:
                # Content was UTF-8 but decoded as Latin-1, re-encode
                fixed = content.encode('latin-1').decode('utf-8')
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

        # Try to detect and fix BOM
        if content.startswith('\ufeff'):
            content = content[1:]

        return content

    def _try_decode(self, raw_bytes: bytes) -> str:
        """Try multiple encodings to decode bytes"""
        # Try encodings in order of likelihood for German data
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']

        for encoding in encodings:
            try:
                decoded = raw_bytes.decode(encoding)
                # Check if it looks reasonable (no excessive replacement chars)
                if '\ufffd' not in decoded[:1000]:
                    return decoded
            except (UnicodeDecodeError, UnicodeError):
                continue

        # Fallback: decode with replacement
        return raw_bytes.decode('utf-8', errors='replace')

    def parse(self, source: str, **kwargs) -> ParseResult:
        try:
            if not source:
                return ParseResult(
                    success=False, geojson=None, feature_count=0,
                    has_geometry=False, error="Empty source", format_detected='csv'
                )

            if source.startswith('http'):
                # Fetch as bytes first to handle encoding properly
                response = requests.get(source, timeout=60)
                response.raise_for_status()
                content = self._try_decode(response.content)
            else:
                content = source

            # Fix any encoding issues
            content = self._fix_encoding(content)

            if not content or len(content.strip()) == 0:
                return ParseResult(
                    success=True,
                    geojson={"type": "FeatureCollection", "features": []},
                    feature_count=0, has_geometry=False, format_detected='csv'
                )

            # Try different delimiters
            rows = []
            for delimiter in [',', ';', '\t']:
                try:
                    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
                    rows = list(reader)
                    if rows and len(rows[0]) > 1:
                        break
                except Exception:
                    continue

            if not rows:
                return ParseResult(
                    success=True,
                    geojson={"type": "FeatureCollection", "features": []},
                    feature_count=0,
                    has_geometry=False,
                    format_detected='csv'
                )

            headers = list(rows[0].keys())
            coord_cols = self._detect_coordinate_columns(headers)
            district_col = self._detect_district_column(headers)
            has_coords = coord_cols['lat'] and coord_cols['lon']

            features = []
            for row in rows:
                try:
                    geometry = None
                    properties = dict(row)

                    # Add district info if detected
                    if district_col:
                        raw_district = row.get(district_col, '')
                        properties['_district_column'] = district_col
                        properties['_district_value'] = raw_district
                        # Parse and normalize district number
                        district_num = parse_district_number(raw_district)
                        if district_num:
                            properties['_district_number'] = district_num

                    if has_coords:
                        lat_str = row.get(coord_cols['lat'], '').strip()
                        lon_str = row.get(coord_cols['lon'], '').strip()

                        if lat_str and lon_str:
                            try:
                                lat = parse_german_number(lat_str)
                                lon = parse_german_number(lon_str)
                                if lat is None or lon is None:
                                    raise ValueError("Invalid coordinate")

                                # Check if coordinates need transformation
                                if CoordinateTransformer.is_utm32n(lon, lat):
                                    lon, lat = CoordinateTransformer.utm32n_to_wgs84(lon, lat)
                                elif CoordinateTransformer.is_utm32n(lat, lon):
                                    # Columns might be swapped
                                    lon, lat = CoordinateTransformer.utm32n_to_wgs84(lat, lon)

                                # Validate WGS84 coordinates
                                if CoordinateTransformer.is_wgs84(lon, lat):
                                    geometry = {
                                        "type": "Point",
                                        "coordinates": [lon, lat]
                                    }
                                    # Remove coord columns from properties
                                    properties = {k: v for k, v in row.items()
                                                if k not in [coord_cols['lat'], coord_cols['lon']]}
                            except ValueError:
                                pass

                    features.append({
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": properties
                    })
                except Exception as e:
                    logger.debug(f"Error parsing CSV row: {e}")
                    continue

            geo_features = [f for f in features if f['geometry'] is not None]

            return ParseResult(
                success=True,
                geojson={"type": "FeatureCollection", "features": features},
                feature_count=len(features),
                has_geometry=len(geo_features) > 0,
                format_detected='csv'
            )

        except Exception as e:
            # Only log at debug level - many failures are expected
            logger.debug(f"CSV parse error: {e}")
            return ParseResult(
                success=False,
                geojson=None,
                feature_count=0,
                has_geometry=False,
                error=str(e),
                format_detected='csv'
            )

    def _detect_coordinate_columns(self, headers: List[str]) -> Dict[str, Optional[str]]:
        """Detect latitude and longitude columns"""
        headers_lower = [h.lower().strip() for h in headers]
        lat_col = None
        lon_col = None

        # Exact match first
        for i, h in enumerate(headers_lower):
            if not lat_col:
                for pattern in self.LAT_PATTERNS:
                    if pattern == h:
                        lat_col = headers[i]
                        break
            if not lon_col:
                for pattern in self.LON_PATTERNS:
                    if pattern == h:
                        lon_col = headers[i]
                        break

        # Partial match
        if not lat_col or not lon_col:
            for i, h in enumerate(headers_lower):
                if not lat_col:
                    for pattern in self.LAT_PATTERNS:
                        if pattern in h:
                            lat_col = headers[i]
                            break
                if not lon_col:
                    for pattern in self.LON_PATTERNS:
                        if pattern in h:
                            lon_col = headers[i]
                            break

        return {'lat': lat_col, 'lon': lon_col}

    def _detect_district_column(self, headers: List[str]) -> Optional[str]:
        """Detect district column"""
        headers_lower = [h.lower().strip() for h in headers]
        for i, h in enumerate(headers_lower):
            for pattern in self.DISTRICT_PATTERNS:
                if pattern in h:
                    return headers[i]
        return None


class GeoJSONParser(BaseParser):
    """Parser for GeoJSON files"""

    def can_parse(self, source: str, content_type: str = None) -> bool:
        if not source:
            return False
        if content_type and 'geojson' in content_type.lower():
            return True
        source_lower = source.lower() if isinstance(source, str) else ''
        return (source_lower.endswith('.geojson') or
                'outputformat=application/json' in source_lower or
                'outputformat=geojson' in source_lower)

    def parse(self, source: str, **kwargs) -> ParseResult:
        try:
            if not source:
                return ParseResult(
                    success=False, geojson=None, feature_count=0,
                    has_geometry=False, error="Empty source", format_detected='geojson'
                )

            if isinstance(source, str) and source.startswith('http'):
                content, _ = self._fetch_url(source)
                if not content or not content.strip():
                    return ParseResult(
                        success=False, geojson=None, feature_count=0,
                        has_geometry=False, error="Empty response", format_detected='geojson'
                    )
                data = json.loads(content)
            elif isinstance(source, str):
                if not source.strip():
                    return ParseResult(
                        success=False, geojson=None, feature_count=0,
                        has_geometry=False, error="Empty content", format_detected='geojson'
                    )
                data = json.loads(source)
            else:
                data = source

            # Detect CRS
            source_crs = None
            if 'crs' in data:
                crs_props = data.get('crs', {}).get('properties', {})
                source_crs = crs_props.get('name', '')

            # Handle different GeoJSON structures
            if data.get('type') == 'FeatureCollection':
                features = data.get('features', [])
            elif data.get('type') == 'Feature':
                features = [data]
            else:
                # Might be raw geometry
                features = [{'type': 'Feature', 'geometry': data, 'properties': {}}]

            # Transform coordinates if needed
            transformed_features = []
            for feature in features:
                if feature.get('geometry'):
                    feature['geometry'] = CoordinateTransformer.transform_geometry(
                        feature['geometry'],
                        source_crs
                    )
                transformed_features.append(feature)

            geo_features = [f for f in transformed_features if f.get('geometry') is not None]

            return ParseResult(
                success=True,
                geojson={"type": "FeatureCollection", "features": transformed_features},
                feature_count=len(transformed_features),
                has_geometry=len(geo_features) > 0,
                source_crs=source_crs,
                format_detected='geojson'
            )

        except Exception as e:
            logger.debug(f"GeoJSON parse error: {e}")
            return ParseResult(
                success=False,
                geojson=None,
                feature_count=0,
                has_geometry=False,
                error=str(e),
                format_detected='geojson'
            )


class JSONParser(BaseParser):
    """Parser for generic JSON files (attempts to extract features)"""

    def can_parse(self, source: str, content_type: str = None) -> bool:
        if content_type and 'json' in content_type.lower() and 'geojson' not in content_type.lower():
            return True
        return source.lower().endswith('.json')

    def parse(self, source: str, **kwargs) -> ParseResult:
        try:
            if source.startswith('http'):
                content, _ = self._fetch_url(source)
                data = json.loads(content)
            else:
                data = json.loads(source) if isinstance(source, str) else source

            # Try GeoJSON first
            if data.get('type') in ['FeatureCollection', 'Feature']:
                return GeoJSONParser().parse(json.dumps(data))

            # Convert array to features
            if isinstance(data, list):
                features = [
                    {"type": "Feature", "geometry": None, "properties": item if isinstance(item, dict) else {"value": item}}
                    for item in data
                ]
            elif isinstance(data, dict):
                # Look for array in common keys
                array_keys = ['data', 'results', 'items', 'records', 'features']
                items = None
                for key in array_keys:
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break

                if items:
                    features = [
                        {"type": "Feature", "geometry": None, "properties": item if isinstance(item, dict) else {"value": item}}
                        for item in items
                    ]
                else:
                    features = [{"type": "Feature", "geometry": None, "properties": data}]
            else:
                features = []

            return ParseResult(
                success=True,
                geojson={"type": "FeatureCollection", "features": features},
                feature_count=len(features),
                has_geometry=False,
                format_detected='json'
            )

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return ParseResult(
                success=False,
                geojson=None,
                feature_count=0,
                has_geometry=False,
                error=str(e),
                format_detected='json'
            )


class WFSParser(BaseParser):
    """Parser for WFS (Web Feature Service) endpoints"""

    def can_parse(self, source: str, content_type: str = None) -> bool:
        return 'wfs' in source.lower() or 'service=wfs' in source.lower()

    def parse(self, source: str, **kwargs) -> ParseResult:
        try:
            # Modify URL to request GeoJSON output
            url = source
            if 'outputformat=' not in url.lower():
                separator = '&' if '?' in url else '?'
                url = f"{url}{separator}outputFormat=application/json"

            content, content_type = self._fetch_url(url)

            # Parse as GeoJSON
            return GeoJSONParser().parse(content)

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return ParseResult(
                success=False,
                geojson=None,
                feature_count=0,
                has_geometry=False,
                error=str(e),
                format_detected='wfs'
            )


class WMSParser(BaseParser):
    """Parser for WMS (Web Map Service) - returns tile URL info, not features"""

    def can_parse(self, source: str, content_type: str = None) -> bool:
        return 'wms' in source.lower() or 'service=wms' in source.lower()

    def parse(self, source: str, **kwargs) -> ParseResult:
        # WMS is a raster tile service, we just return metadata about it
        return ParseResult(
            success=True,
            geojson={
                "type": "FeatureCollection",
                "features": [],
                "_wms_url": source,
                "_is_raster": True
            },
            feature_count=0,
            has_geometry=False,
            format_detected='wms'
        )


class ShapefileParser(BaseParser):
    """Parser for Shapefiles (usually in ZIP archives)"""

    def can_parse(self, source: str, content_type: str = None) -> bool:
        lower = source.lower()
        return (lower.endswith('.shp') or lower.endswith('.zip') or
                'shape' in lower or content_type and 'zip' in content_type.lower())

    def parse(self, source: str, **kwargs) -> ParseResult:
        try:
            # Try importing geopandas/fiona
            try:
                import geopandas as gpd
            except ImportError:
                return ParseResult(
                    success=False,
                    geojson=None,
                    feature_count=0,
                    has_geometry=False,
                    error="geopandas not installed - required for Shapefile parsing",
                    format_detected='shapefile'
                )

            if source.startswith('http'):
                content, _ = self._fetch_binary(source)

                # Handle ZIP file
                with tempfile.TemporaryDirectory() as tmpdir:
                    if content[:4] == b'PK\x03\x04':  # ZIP magic number
                        zip_path = f"{tmpdir}/data.zip"
                        with open(zip_path, 'wb') as f:
                            f.write(content)

                        with zipfile.ZipFile(zip_path, 'r') as zf:
                            zf.extractall(tmpdir)

                        # Find .shp file
                        import os
                        shp_files = []
                        for root, dirs, files in os.walk(tmpdir):
                            shp_files.extend([
                                os.path.join(root, f) for f in files if f.endswith('.shp')
                            ])

                        if not shp_files:
                            return ParseResult(
                                success=False,
                                geojson=None,
                                feature_count=0,
                                has_geometry=False,
                                error="No .shp file found in ZIP archive",
                                format_detected='shapefile'
                            )

                        gdf = gpd.read_file(shp_files[0])
                    else:
                        # Direct shapefile
                        shp_path = f"{tmpdir}/data.shp"
                        with open(shp_path, 'wb') as f:
                            f.write(content)
                        gdf = gpd.read_file(shp_path)
            else:
                gdf = gpd.read_file(source)

            # Convert to WGS84 if needed
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)

            # Convert to GeoJSON
            geojson_str = gdf.to_json()
            geojson = json.loads(geojson_str)

            geo_features = [f for f in geojson['features'] if f.get('geometry') is not None]

            return ParseResult(
                success=True,
                geojson=geojson,
                feature_count=len(geojson['features']),
                has_geometry=len(geo_features) > 0,
                format_detected='shapefile'
            )

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return ParseResult(
                success=False,
                geojson=None,
                feature_count=0,
                has_geometry=False,
                error=str(e),
                format_detected='shapefile'
            )


class XMLParser(BaseParser):
    """Parser for XML files (attempts to extract tabular data)"""

    def can_parse(self, source: str, content_type: str = None) -> bool:
        if content_type and ('xml' in content_type.lower() and 'gml' not in content_type.lower()):
            return True
        return source.lower().endswith('.xml')

    def parse(self, source: str, **kwargs) -> ParseResult:
        try:
            if source.startswith('http'):
                content, _ = self._fetch_url(source)
            else:
                content = source

            root = ET.fromstring(content)

            # Try to find repeating elements (records)
            features = []

            # Common patterns: look for repeated child elements
            child_tags = {}
            for child in root:
                tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                child_tags[tag] = child_tags.get(tag, 0) + 1

            # Find the most common repeating element
            if child_tags:
                record_tag = max(child_tags, key=child_tags.get)
                if child_tags[record_tag] > 1:
                    for elem in root.iter():
                        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                        if tag == record_tag:
                            props = {}
                            for child in elem:
                                child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                                props[child_tag] = child.text or ''
                            if props:
                                features.append({
                                    "type": "Feature",
                                    "geometry": None,
                                    "properties": props
                                })

            return ParseResult(
                success=True,
                geojson={"type": "FeatureCollection", "features": features},
                feature_count=len(features),
                has_geometry=False,
                format_detected='xml'
            )

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return ParseResult(
                success=False,
                geojson=None,
                feature_count=0,
                has_geometry=False,
                error=str(e),
                format_detected='xml'
            )


class GMLParser(BaseParser):
    """Parser for GML (Geography Markup Language) files"""

    def can_parse(self, source: str, content_type: str = None) -> bool:
        if content_type and 'gml' in content_type.lower():
            return True
        return source.lower().endswith('.gml') or 'outputformat=gml' in source.lower()

    def parse(self, source: str, **kwargs) -> ParseResult:
        try:
            # Try using geopandas for GML
            try:
                import geopandas as gpd

                if source.startswith('http'):
                    content, _ = self._fetch_url(source)
                    with tempfile.NamedTemporaryFile(suffix='.gml', delete=False) as f:
                        f.write(content.encode())
                        f.flush()
                        gdf = gpd.read_file(f.name)
                else:
                    gdf = gpd.read_file(source)

                # Convert to WGS84
                if gdf.crs and gdf.crs.to_epsg() != 4326:
                    gdf = gdf.to_crs(epsg=4326)

                geojson_str = gdf.to_json()
                geojson = json.loads(geojson_str)

                geo_features = [f for f in geojson['features'] if f.get('geometry') is not None]

                return ParseResult(
                    success=True,
                    geojson=geojson,
                    feature_count=len(geojson['features']),
                    has_geometry=len(geo_features) > 0,
                    format_detected='gml'
                )

            except ImportError:
                # Fallback to basic XML parsing
                return XMLParser().parse(source)

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return ParseResult(
                success=False,
                geojson=None,
                feature_count=0,
                has_geometry=False,
                error=str(e),
                format_detected='gml'
            )


class DataParser:
    """Unified parser that automatically selects the right parser for the data format"""

    # Format priority for parsing attempts
    FORMAT_PRIORITY = ['geojson', 'wfs', 'json', 'csv', 'gml', 'shapefile', 'shape', 'zip', 'xml', 'wms']

    def __init__(self):
        self.parsers = {
            'csv': CSVParser(),
            'geojson': GeoJSONParser(),
            'json': JSONParser(),
            'wfs': WFSParser(),
            'wms': WMSParser(),
            'shapefile': ShapefileParser(),
            'shape': ShapefileParser(),
            'zip': ShapefileParser(),
            'xml': XMLParser(),
            'gml': GMLParser(),
        }

    def parse(self, url: str, format_hint: str = None) -> ParseResult:
        """
        Parse data from URL, auto-detecting format if not specified.
        Returns unified GeoJSON FeatureCollection.
        """
        # Try format hint first
        if format_hint:
            format_lower = format_hint.lower()
            parser = self.parsers.get(format_lower)
            if parser:
                result = parser.parse(url)
                if result.success:
                    return result

        # Auto-detect based on URL patterns
        url_lower = url.lower()

        for fmt in self.FORMAT_PRIORITY:
            parser = self.parsers.get(fmt)
            if parser and parser.can_parse(url):
                result = parser.parse(url)
                if result.success:
                    return result

        # Fallback: try each parser
        for fmt in self.FORMAT_PRIORITY:
            parser = self.parsers.get(fmt)
            if parser:
                try:
                    result = parser.parse(url)
                    if result.success and result.feature_count > 0:
                        return result
                except:
                    continue

        return ParseResult(
            success=False,
            geojson=None,
            feature_count=0,
            has_geometry=False,
            error="Could not parse data with any available parser"
        )

    def parse_resource(self, resource: Dict[str, Any]) -> ParseResult:
        """Parse a CKAN resource dict"""
        url = resource.get('url', '')
        fmt = resource.get('format', '').lower()
        return self.parse(url, fmt)
