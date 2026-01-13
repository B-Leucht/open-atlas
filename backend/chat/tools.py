"""
Analysis Tools for Munich Open Data
DuckDB-based CSV and geospatial data analysis
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


def _extract_coordinates(df: pd.DataFrame, max_points: int = 200) -> Optional[List[Dict[str, float]]]:
    """
    Extract coordinates from a DataFrame.

    Checks for:
    1. Explicit lat/lon columns
    2. WKT geometry strings (POINT(lon lat))
    3. Geometry column with WKT

    Returns list of {lat, lon} dicts or None if no coordinates found.
    """
    coords = []
    logger.info(f"Extracting coordinates from DataFrame with columns: {list(df.columns)}")

    # Method 1: Check for explicit lat/lon columns
    lat_cols = [c for c in df.columns if c.lower() in ("lat", "latitude", "y")]
    lon_cols = [c for c in df.columns if c.lower() in ("lon", "longitude", "x")]

    if lat_cols and lon_cols:
        for _, row in df.head(max_points).iterrows():
            try:
                lat = float(row[lat_cols[0]])
                lon = float(row[lon_cols[0]])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    coords.append({"lat": lat, "lon": lon})
            except (ValueError, TypeError):
                continue
        if coords:
            return coords

    # Method 2: Check for geometry columns with WKT POINT format
    geom_cols = [c for c in df.columns if c.lower() in ("geometry", "geom", "wkb_geometry", "the_geom", "shape")]
    logger.info(f"Found geometry columns: {geom_cols}")

    for geom_col in geom_cols:
        logger.info(f"Checking geometry column '{geom_col}'")
        # Sample first few values to see what we're working with
        sample_values = df[geom_col].head(3).tolist()
        logger.info(f"Sample values from '{geom_col}': {sample_values}")
        # Also log the type of the first value
        if len(df) > 0 and df[geom_col].iloc[0] is not None:
            first_val = df[geom_col].iloc[0]
            logger.info(f"Type of first value: {type(first_val)}, repr: {repr(first_val)[:200]}")

        for _, row in df.head(max_points).iterrows():
            geom = row.get(geom_col)
            if geom:
                # Convert to string representation for parsing
                geom_str = str(geom)
                point = _parse_wkt_point(geom_str)
                if point:
                    coords.append(point)
                elif len(coords) == 0:
                    # Log first failure to help debugging
                    logger.debug(f"Could not parse geometry: {geom_str[:100]}")
        if coords:
            logger.info(f"Extracted {len(coords)} coordinates from column '{geom_col}'")
            return coords
        else:
            logger.info(f"No coordinates extracted from column '{geom_col}'")

    # Method 3: Check ALL columns for WKT POINT strings
    for col in df.columns:
        sample = df[col].head(5).astype(str).tolist()
        if any("POINT" in str(s).upper() for s in sample):
            logger.info(f"Found POINT data in column '{col}', extracting coordinates...")
            for _, row in df.head(max_points).iterrows():
                val = row.get(col)
                if val:
                    point = _parse_wkt_point(str(val))
                    if point:
                        coords.append(point)
            logger.info(f"Extracted {len(coords)} coordinates from column '{col}'")
            if coords:
                return coords

    logger.info(f"Total coordinates extracted: {len(coords) if coords else 0}")
    return coords if coords else None


def _parse_wkt_point(wkt: str) -> Optional[Dict[str, float]]:
    """
    Parse WKT POINT geometry to extract lat/lon.

    Handles formats:
    - POINT (lon lat) - WGS84
    - POINT(lon lat)
    - POINT Z (lon lat z)
    - POINT (x y) - UTM/EPSG:25832 (auto-detected and converted)
    """
    if not wkt or "POINT" not in wkt.upper():
        return None

    # Match POINT with optional Z/M modifiers: POINT (lon lat) or POINT Z (lon lat z)
    match = re.search(r'POINT\s*[ZM]*\s*\(\s*([-\d.]+)\s+([-\d.]+)', wkt, re.IGNORECASE)
    if not match:
        logger.debug(f"No POINT match found in: {wkt[:100]}")
        return None

    try:
        x = float(match.group(1))
        y = float(match.group(2))

        # Check if coordinates are in UTM (EPSG:25832) - Munich area values
        # UTM zone 32N for Munich: x ~ 680000-700000, y ~ 5320000-5350000
        if x > 100000 and y > 1000000:
            # Convert from EPSG:25832 (UTM zone 32N) to WGS84
            lon, lat = _convert_utm_to_wgs84(x, y)
            if lon is not None and lat is not None:
                logger.debug(f"UTM ({x}, {y}) -> WGS84 ({lon:.6f}, {lat:.6f})")
                return {"lat": lat, "lon": lon}
            else:
                logger.warning(f"UTM conversion failed for ({x}, {y})")
        else:
            # Assume WGS84 coordinates
            lon, lat = x, y
            # Sanity check for valid WGS84 coordinates
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                return {"lat": lat, "lon": lon}
    except (ValueError, TypeError):
        pass

    return None


def _convert_utm_to_wgs84(x: float, y: float) -> tuple:
    """
    Convert UTM coordinates (EPSG:25832) to WGS84 (EPSG:4326).

    Args:
        x: Easting in meters
        y: Northing in meters

    Returns:
        (longitude, latitude) tuple or (None, None) if conversion fails
    """
    try:
        import pyproj

        # Define coordinate systems
        utm = pyproj.CRS("EPSG:25832")  # UTM zone 32N
        wgs84 = pyproj.CRS("EPSG:4326")  # WGS84

        transformer = pyproj.Transformer.from_crs(utm, wgs84, always_xy=True)
        lon, lat = transformer.transform(x, y)

        # Validate result
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            return lon, lat
    except ImportError:
        logger.info("pyproj not available, using simplified UTM conversion")
        # Simplified but accurate enough conversion for Munich area
        # Based on the UTM zone 32N projection parameters
        return _simple_utm_to_wgs84(x, y)
    except Exception as e:
        logger.warning(f"pyproj conversion failed: {e}, trying fallback")
        return _simple_utm_to_wgs84(x, y)

    return None, None


def _simple_utm_to_wgs84(x: float, y: float) -> tuple:
    """
    Simplified UTM to WGS84 conversion for Munich area.
    Uses linear approximation that's accurate within ~100m for the Munich region.
    """
    try:
        # For Munich area (UTM zone 32N):
        # Reference point: Munich city center
        # UTM: 691750, 5334500 -> WGS84: 11.576, 48.137

        # Linear approximation coefficients for Munich area
        # 1 degree longitude ≈ 73000m at lat 48°
        # 1 degree latitude ≈ 111000m

        # Reference point (Munich Marienplatz approximate)
        ref_x = 691750
        ref_y = 5334500
        ref_lon = 11.576
        ref_lat = 48.137

        # Scale factors
        m_per_deg_lon = 73000  # meters per degree longitude at lat 48
        m_per_deg_lat = 111000  # meters per degree latitude

        # Calculate offset from reference
        dx = x - ref_x
        dy = y - ref_y

        # Convert to degrees
        lon = ref_lon + (dx / m_per_deg_lon)
        lat = ref_lat + (dy / m_per_deg_lat)

        # Validate Munich area
        if 10.5 < lon < 12.5 and 47.5 < lat < 49.0:
            return lon, lat
        else:
            logger.warning(f"Converted coordinates ({lon:.4f}, {lat:.4f}) outside Munich area")
            return lon, lat  # Return anyway, might be valid
    except Exception as e:
        logger.warning(f"Simple UTM conversion failed: {e}")

    return None, None


def select_best_resource(resources: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Choose the best resource for analysis.
    Priority: CSV > GEOJSON > WFS > JSON
    """
    if not resources:
        return None

    priority = {"CSV": 0, "GEOJSON": 1, "WFS": 2, "JSON": 3}

    def score(res):
        fmt = (res.get("format") or "").upper()
        return priority.get(fmt, 99), res.get("name") or ""

    return sorted(resources, key=score)[0]


def generate_sql(user_query: str, columns: List[str], preview_md: str,
                 table_name: str, spatial: bool = False) -> str:
    """Generate SQL query using LLM"""
    llm = ChatOpenAI(model="gpt-5-mini", temperature=0.1)

    spatial_hint = ""
    if spatial:
        spatial_hint = (
            "- You may use DuckDB spatial functions like ST_Distance, ST_Within, ST_Point.\n"
        )

    system_msg = AIMessage(content=(
        f"You are a data analyst writing DuckDB SQL over a table named `{table_name}`.\n"
        "- Use ONLY the available columns.\n"
        "- Your query MUST be a single SELECT statement.\n"
        "- You MAY use WHERE, GROUP BY, ORDER BY, and LIMIT clauses.\n"
        "- You MUST NOT use JOINs, subqueries, CTEs, or modify data.\n"
        f"{spatial_hint}"
        "- Prefer aggregates when they answer the question well.\n"
        "- Return ONLY the SQL query, no explanations."
    ))

    user_msg = HumanMessage(content=(
        f"User question:\n{user_query}\n\n"
        f"Available columns:\n{columns}\n\n"
        f"Sample rows:\n{preview_md}\n\n"
        f"Write a SQL query over `{table_name}` that answers the question."
    ))

    response = llm.invoke([system_msg, user_msg])
    sql_query = (response.content or "").strip()

    # Basic safety check
    lower_sql = sql_query.lower()
    bad_keywords = [" join ", " with ", ";", " insert ", " update ", " delete ", " create ", " drop "]
    if ("select" not in lower_sql or f" from {table_name}" not in lower_sql or
            any(bad in lower_sql for bad in bad_keywords)):
        sql_query = f"SELECT * FROM {table_name} LIMIT 500"

    return sql_query


def analyze_csv(url: str, user_query: str) -> Dict[str, Any]:
    """
    Analyze CSV data with LLM-generated SQL.
    Downloads CSV, registers with DuckDB, generates and executes SQL.
    """
    conn = duckdb.connect()
    try:
        # Download and register CSV
        try:
            df = pd.read_csv(url)
        except Exception as e:
            return {
                "kind": "csv",
                "error": "download_failed",
                "error_message": "Could not download CSV file.",
                "exception": str(e),
            }

        conn.register("tab", df)

        # Get preview
        preview_df = conn.execute("SELECT * FROM tab LIMIT 200").fetch_df()
        columns = list(preview_df.columns)
        preview_md = preview_df.head(20).to_markdown(index=False)

        # Generate SQL with LLM
        sql_query = generate_sql(user_query, columns, preview_md, "tab")

        # Execute query
        try:
            result_df = conn.execute(sql_query).fetch_df()
        except Exception as e:
            logger.debug(f"SQL failed, using fallback: {e}")
            # Fallback to simple preview
            result_df = preview_df
            sql_query = "SELECT * FROM tab LIMIT 200"

        # Extract coordinates if present (CSV might have lat/lon columns)
        logger.info(f"CSV analysis: extracting coordinates from result with columns {list(result_df.columns)}")
        coords = _extract_coordinates(result_df)
        logger.info(f"CSV coordinate extraction result: {len(coords) if coords else 0} coordinates")

        # Get display columns (exclude coordinate columns from table display if coordinates were found)
        if coords:
            display_cols = _get_display_columns(result_df)
            display_df = result_df[display_cols] if display_cols else result_df
        else:
            display_cols = list(result_df.columns)
            display_df = result_df

        result = {
            "kind": "csv",
            "sql_query": sql_query,
            "preview_markdown": display_df.head(200).to_markdown(index=False),
            "columns": display_cols,
            "row_count": len(result_df),
        }

        if coords:
            result["coordinates"] = coords

        return result

    finally:
        conn.close()


def _get_display_columns(df: pd.DataFrame) -> List[str]:
    """
    Get columns suitable for display, excluding coordinate/geometry columns.
    These columns are still used for map display but hidden from the table.
    """
    exclude_patterns = [
        'geometry', 'geom', 'wkb_geometry', 'the_geom', 'shape',
        'lat', 'latitude', 'lon', 'longitude', 'x', 'y',
        'rechtswert', 'hochwert', 'easting', 'northing'
    ]
    display_cols = []
    for col in df.columns:
        col_lower = col.lower()
        # Exclude geometry columns and coordinate columns
        if not any(pattern in col_lower for pattern in exclude_patterns):
            # Also exclude columns that look like raw coordinate values
            sample = df[col].head(5).astype(str).tolist()
            if not any("POINT" in str(s).upper() for s in sample):
                display_cols.append(col)
    return display_cols


def analyze_geospatial(url: str, user_query: str) -> Dict[str, Any]:
    """
    Analyze geospatial data with DuckDB spatial extension.
    Loads GeoJSON/WFS, generates and executes spatial SQL.
    """
    logger.info(f"analyze_geospatial called with url={url[:80]}...")
    conn = duckdb.connect()
    try:
        # Load extensions
        conn.execute("SET allow_unsigned_extensions=true;")
        duckdb.install_extension("httpfs")
        duckdb.load_extension("httpfs")
        duckdb.install_extension("spatial")
        duckdb.load_extension("spatial")

        # Create view from geospatial file
        conn.execute("CREATE OR REPLACE VIEW geo AS SELECT * FROM ST_Read(?);", [url])

        # Get preview
        preview_df = conn.execute("SELECT * FROM geo LIMIT 200").fetch_df()
        columns = list(preview_df.columns)
        logger.info(f"Loaded geospatial data with columns: {columns}")
        preview_md = preview_df.head(20).to_markdown(index=False)

        # Generate SQL
        sql_query = generate_sql(user_query, columns, preview_md, "geo", spatial=True)
        logger.info(f"Generated SQL: {sql_query[:100]}...")

        # Execute query
        try:
            result_df = conn.execute(sql_query).fetch_df()
            logger.info(f"SQL executed, result has {len(result_df)} rows and columns: {list(result_df.columns)}")
        except Exception as e:
            logger.debug(f"Spatial SQL failed, using fallback: {e}")
            result_df = preview_df
            sql_query = "SELECT * FROM geo LIMIT 200"

        # Extract coordinates if present (before filtering columns)
        logger.info(f"Calling _extract_coordinates with DataFrame of shape {result_df.shape}")
        coords = _extract_coordinates(result_df)
        logger.info(f"_extract_coordinates returned: {len(coords) if coords else 0} coordinates")

        # Get display columns (exclude geometry/coordinate columns from table display)
        display_cols = _get_display_columns(result_df)
        display_df = result_df[display_cols] if display_cols else result_df

        result = {
            "kind": "geospatial",
            "sql_query": sql_query,
            "preview_markdown": display_df.head(200).to_markdown(index=False),
            "columns": display_cols,
            "row_count": len(result_df),
        }

        if coords:
            result["coordinates"] = coords

        return result

    except Exception as e:
        return {
            "kind": "geospatial",
            "error": "query_failed",
            "error_message": "Could not load or query geospatial data.",
            "exception": str(e),
        }
    finally:
        conn.close()


def query_tabular(url: str, sql_query: str) -> Dict[str, Any]:
    """
    Execute a SQL query against a remote CSV using DuckDB.
    The table is registered as `tab`.
    """
    conn = duckdb.connect()
    try:
        try:
            df = pd.read_csv(url)
        except Exception as e:
            return {
                "kind": "tabular",
                "url": url,
                "sql_query": sql_query,
                "error": "download_failed",
                "error_message": "Could not download CSV file.",
                "exception": str(e),
            }

        conn.register("tab", df)
        result_df = conn.execute(sql_query).fetch_df()

        return {
            "kind": "tabular",
            "url": url,
            "sql_query": sql_query,
            "preview_markdown": result_df.head(200).to_markdown(index=False),
            "columns": list(result_df.columns),
            "row_count": len(result_df),
        }

    except Exception as e:
        return {
            "kind": "tabular",
            "url": url,
            "sql_query": sql_query,
            "error": "query_failed",
            "error_message": "SQL query failed.",
            "exception": str(e),
        }
    finally:
        conn.close()


def query_geospatial(url: str, sql_query: str) -> Dict[str, Any]:
    """
    Execute a geospatial SQL query using DuckDB spatial.
    The data is registered as `geo`.
    """
    conn = duckdb.connect()
    try:
        conn.execute("SET allow_unsigned_extensions=true;")
        duckdb.install_extension("httpfs")
        duckdb.load_extension("httpfs")
        duckdb.install_extension("spatial")
        duckdb.load_extension("spatial")

        conn.execute("CREATE OR REPLACE VIEW geo AS SELECT * FROM ST_Read(?);", [url])
        result_df = conn.execute(sql_query).fetch_df()

        return {
            "kind": "geospatial",
            "url": url,
            "sql_query": sql_query,
            "preview_markdown": result_df.head(200).to_markdown(index=False),
            "columns": list(result_df.columns),
            "row_count": len(result_df),
        }

    except Exception as e:
        return {
            "kind": "geospatial",
            "url": url,
            "sql_query": sql_query,
            "error": "query_failed",
            "error_message": "Geospatial query failed.",
            "exception": str(e),
        }
    finally:
        conn.close()


# =============================================================================
# QUERY CLASSIFICATION
# =============================================================================

# Keywords for classification fallback heuristics
INDEX_KEYWORDS = [
    "best", "worst", "rank", "ranking", "score", "rate", "rating",
    "most", "least", "top districts", "which district is",
    "friendliest", "safest", "greenest", "livable", "livability"
]

MULTI_KEYWORDS = [
    "compare", "comparison", "versus", " vs ", " and ",
    "both", "relationship", "correlation", "between",
    "across datasets", "multiple"
]


def classify_query(user_query: str) -> Dict[str, Any]:
    """
    Classify user query to determine processing path.

    Returns:
        {
            "query_type": "single_dataset" | "multi_dataset" | "index_creation",
            "reasoning": str,
            "confidence": float
        }
    """
    llm = ChatOpenAI(model="gpt-5-mini", temperature=0.0)

    system_msg = AIMessage(content="""You classify user queries about Munich open data into exactly ONE category.

Categories:
1. SINGLE_DATASET - Simple factual queries about one topic
   Examples: "How many schools are in Munich?", "Show me all parks", "Where are the playgrounds?"

2. MULTI_DATASET - Comparative queries requiring data from multiple sources
   Examples: "Compare schools and hospitals by district", "What's the relationship between parks and population?"
   Keywords: compare, versus, both, relationship, correlation

3. INDEX_CREATION - Ranking/scoring queries that need to combine multiple factors
   Examples: "Which district is best for families?", "Rank districts by livability", "Score districts for seniors"
   Keywords: best, worst, rank, score, rate, top, most, least, -friendliest, -safest

Return ONLY valid JSON:
{"query_type": "single_dataset" | "multi_dataset" | "index_creation", "reasoning": "brief explanation", "confidence": 0.0-1.0}""")

    user_msg = HumanMessage(content=f"Classify this query: {user_query}")

    try:
        response = llm.invoke([system_msg, user_msg])
        content = response.content.strip()

        # Parse JSON response
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        result = json.loads(content)

        # Validate query_type
        valid_types = ["single_dataset", "multi_dataset", "index_creation"]
        if result.get("query_type") not in valid_types:
            raise ValueError(f"Invalid query_type: {result.get('query_type')}")

        return result

    except Exception as e:
        logger.warning(f"LLM classification failed, using heuristics: {e}")
        return _classify_query_heuristic(user_query)


def _classify_query_heuristic(user_query: str) -> Dict[str, Any]:
    """Fallback classification using keyword matching"""
    query_lower = user_query.lower()

    # Check for index creation keywords first (most specific)
    for kw in INDEX_KEYWORDS:
        if kw in query_lower:
            return {
                "query_type": "index_creation",
                "reasoning": f"Detected ranking keyword: '{kw}'",
                "confidence": 0.7
            }

    # Check for multi-dataset keywords
    for kw in MULTI_KEYWORDS:
        if kw in query_lower:
            return {
                "query_type": "multi_dataset",
                "reasoning": f"Detected comparison keyword: '{kw}'",
                "confidence": 0.7
            }

    # Default to single dataset
    return {
        "query_type": "single_dataset",
        "reasoning": "No comparison or ranking keywords detected",
        "confidence": 0.6
    }


# =============================================================================
# MULTI-DATASET ANALYSIS
# =============================================================================

def analyze_multiple_datasets(
    datasets: List[Dict[str, Any]],
    user_query: str
) -> Dict[str, Any]:
    """
    Analyze multiple datasets and produce combined insights.

    Args:
        datasets: List of dataset metadata with resources
        user_query: Original user question

    Returns:
        {
            "individual_results": List of per-dataset analysis results,
            "combined_analysis": LLM-synthesized markdown,
            "summary_table": Comparative markdown table
        }
    """
    individual_results = []

    # Analyze each dataset
    for dataset in datasets:
        resource = dataset.get("selected_resource") or {}
        fmt = (resource.get("format") or "").upper()
        url = resource.get("url")

        if not url:
            result = {
                "dataset_title": dataset.get("title"),
                "error": "no_url",
                "error_message": "No resource URL available"
            }
        elif fmt == "CSV":
            result = analyze_csv(url, user_query)
            result["dataset_title"] = dataset.get("title")
        elif fmt in {"GEOJSON", "WFS", "JSON"}:
            result = analyze_geospatial(url, user_query)
            result["dataset_title"] = dataset.get("title")
        else:
            result = {
                "dataset_title": dataset.get("title"),
                "error": "unsupported_format",
                "error_message": f"Format '{fmt}' not supported"
            }

        individual_results.append(result)

    # Filter successful results for synthesis
    successful_results = [r for r in individual_results if not r.get("error")]

    if not successful_results:
        return {
            "individual_results": individual_results,
            "combined_analysis": "Could not analyze any of the selected datasets.",
            "summary_table": ""
        }

    # Synthesize results with LLM
    combined_analysis = _synthesize_multi_results(successful_results, user_query)

    return {
        "individual_results": individual_results,
        "combined_analysis": combined_analysis,
        "summary_table": _create_summary_table(successful_results)
    }


def _synthesize_multi_results(results: List[Dict[str, Any]], user_query: str) -> str:
    """Use LLM to synthesize insights from multiple dataset analyses"""
    llm = ChatOpenAI(model="gpt-5-mini", temperature=0.1)

    # Build context from results
    results_text = ""
    for i, result in enumerate(results, 1):
        results_text += f"\n### Dataset {i}: {result.get('dataset_title', 'Unknown')}\n"
        results_text += f"SQL: {result.get('sql_query', 'N/A')}\n"
        results_text += f"Rows: {result.get('row_count', 0)}\n"
        results_text += f"Preview:\n{result.get('preview_markdown', 'No data')}\n"

    system_msg = AIMessage(content="""You are a data analyst synthesizing insights from multiple Munich datasets.

Instructions:
- Compare and contrast the datasets
- Identify patterns across the data
- Answer the user's question using ONLY the provided data
- Present key findings in a clear, organized way
- Use markdown formatting
- DO NOT hallucinate data not shown in the previews""")

    user_msg = HumanMessage(content=f"""User question: {user_query}

Dataset analyses:
{results_text}

Synthesize these results to answer the question.""")

    response = llm.invoke([system_msg, user_msg])
    return response.content


def _create_summary_table(results: List[Dict[str, Any]]) -> str:
    """Create a summary comparison table from multiple results"""
    if not results:
        return ""

    rows = []
    for result in results:
        rows.append({
            "Dataset": result.get("dataset_title", "Unknown"),
            "Rows": result.get("row_count", 0),
            "Columns": len(result.get("columns", [])),
            "Type": result.get("kind", "unknown")
        })

    df = pd.DataFrame(rows)
    return df.to_markdown(index=False)


# =============================================================================
# INDEX DESIGN AND CALCULATION
# =============================================================================

import concurrent.futures

# Normalization suggestion rules
NORMALIZATION_RULES = {
    "population": [
        "playground", "school", "kindergarten", "hospital", "doctor",
        "pharmacy", "library", "community center", "childcare",
        "senior center", "care facility", "sports", "kita", "schule"
    ],
    "area": [
        "traffic calming", "tempo 30", "green space", "park",
        "danger", "accident", "wifi", "recycling", "parking",
        "grünfläche", "verkehr"
    ],
    "minmax": [
        "indicator", "rate", "ratio", "percentage", "density",
        "index", "score", "indikator", "dichte", "anteil"
    ]
}


def _select_relevant_from_batch(
    user_query: str,
    batch: List[Dict[str, Any]],
    batch_index: int
) -> List[str]:
    """
    Process a single batch of datasets and return IDs of relevant ones.

    Args:
        user_query: The user's index creation query
        batch: List of dataset dicts to evaluate
        batch_index: Index of this batch (for logging)

    Returns:
        List of dataset IDs that are relevant for the query
    """
    llm = ChatOpenAI(model="gpt-5-mini", temperature=0.0)

    # Format batch with rich details
    batch_text = "\n\n".join([
        f"[{d['id']}] {d['title']}\n"
        f"  Features: {d.get('feature_count', 0)} data points\n"
        f"  District-specific: {'Yes' if d.get('is_district_specific') else 'No'}\n"
        f"  Description: {(d.get('description') or 'No description available')[:250]}"
        for d in batch
    ])

    prompt = f"""You are selecting datasets for creating a district ranking index.

User Query: "{user_query}"

Review each dataset below and determine if it could be relevant for answering this query.
Include datasets that are DIRECTLY relevant (e.g., playgrounds for family-friendliness)
AND datasets that are INDIRECTLY relevant (e.g., traffic calming for safety).

When in doubt, INCLUDE the dataset - it's better to have more options than to miss something useful.

Datasets to review:
{batch_text}

Return a JSON array containing ONLY the IDs of relevant datasets.
Example: ["dataset-id-1", "dataset-id-5", "dataset-id-8"]

If none are relevant, return an empty array: []"""

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()

        # Parse JSON response
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        selected_ids = json.loads(content)

        if not isinstance(selected_ids, list):
            logger.warning(f"Batch {batch_index}: Expected list, got {type(selected_ids)}")
            return []

        logger.info(f"Batch {batch_index}: Selected {len(selected_ids)}/{len(batch)} datasets as relevant")
        return selected_ids

    except Exception as e:
        logger.error(f"Batch {batch_index} selection failed: {e}")
        # On error, return all IDs from batch to avoid losing potentially relevant datasets
        return [d['id'] for d in batch]


def _select_best_datasets(
    user_query: str,
    relevant_datasets: List[Dict[str, Any]],
    max_datasets: int = 10
) -> List[Dict[str, Any]]:
    """
    From all relevant datasets, select the best ones for the index.

    Args:
        user_query: The user's index creation query
        relevant_datasets: Pre-filtered list of relevant datasets
        max_datasets: Maximum number of datasets to select (default 10)

    Returns:
        List of the best datasets for the index (up to max_datasets)
    """
    if len(relevant_datasets) <= max_datasets:
        logger.info(f"Only {len(relevant_datasets)} relevant datasets, using all")
        return relevant_datasets

    llm = ChatOpenAI(model="gpt-5-mini", temperature=0.0)

    # Format all relevant datasets
    dataset_text = "\n\n".join([
        f"[{i+1}] {d['title']} (ID: {d['id']})\n"
        f"    Features: {d.get('feature_count', 0)} | District-specific: {'Yes' if d.get('is_district_specific') else 'No'}\n"
        f"    Description: {(d.get('description') or 'No description')[:200]}"
        for i, d in enumerate(relevant_datasets)
    ])

    prompt = f"""You are finalizing dataset selection for a district ranking index.

User Query: "{user_query}"

From these {len(relevant_datasets)} relevant datasets, select the TOP {max_datasets} that will create the most meaningful and balanced index.

Selection criteria:
1. DIVERSITY: Cover different aspects of the query (e.g., for "family-friendly": include education, safety, recreation, healthcare)
2. DATA QUALITY: Prefer datasets with more features and district-specific data
3. DIRECT RELEVANCE: Prioritize datasets that directly measure what the user is asking about
4. COMPLEMENTARY: Avoid selecting multiple datasets that measure the same thing

Available datasets:
{dataset_text}

Return a JSON array with the numbers (1-{len(relevant_datasets)}) of your top {max_datasets} selections, ordered by importance.
Example: [3, 7, 1, 12, 5, 9, 2, 15, 8, 4]"""

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()

        # Parse JSON
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        selected_indices = json.loads(content)

        if not isinstance(selected_indices, list):
            logger.warning(f"Expected list of indices, got {type(selected_indices)}")
            return relevant_datasets[:max_datasets]

        # Convert 1-indexed to 0-indexed and get datasets
        best_datasets = []
        for idx in selected_indices[:max_datasets]:
            if isinstance(idx, int) and 1 <= idx <= len(relevant_datasets):
                best_datasets.append(relevant_datasets[idx - 1])

        logger.info(f"Selected {len(best_datasets)} best datasets from {len(relevant_datasets)} relevant ones")
        return best_datasets

    except Exception as e:
        logger.error(f"Best dataset selection failed: {e}")
        # Fallback: return first max_datasets sorted by feature count
        return sorted(relevant_datasets, key=lambda x: x.get('feature_count', 0), reverse=True)[:max_datasets]


def select_datasets_for_index(
    user_query: str,
    available_datasets: List[Dict[str, Any]],
    batch_size: int = 10,
    max_final_datasets: int = 10
) -> List[Dict[str, Any]]:
    """
    Two-stage dataset selection for index creation:
    1. Parallel batch processing to find ALL relevant datasets (no limit)
    2. Final selection to pick the best ones (limited to max_final_datasets)

    Args:
        user_query: The user's index creation query
        available_datasets: All datasets from the database
        batch_size: Number of datasets per batch for parallel processing
        max_final_datasets: Maximum datasets in final selection

    Returns:
        List of selected datasets for index design
    """
    # Filter to datasets with features
    useful_datasets = [d for d in available_datasets if d.get('feature_count', 0) > 0]
    logger.info(f"Starting dataset selection: {len(useful_datasets)} datasets with features")

    if len(useful_datasets) <= max_final_datasets:
        logger.info(f"Only {len(useful_datasets)} datasets available, using all")
        return useful_datasets

    # Stage 1: Parallel batch selection to find ALL relevant datasets
    batches = [
        useful_datasets[i:i + batch_size]
        for i in range(0, len(useful_datasets), batch_size)
    ]
    logger.info(f"Stage 1: Processing {len(batches)} batches of ~{batch_size} datasets each")

    # Process batches in parallel using ThreadPoolExecutor
    all_relevant_ids = set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(batches), 5)) as executor:
        # Submit all batch jobs
        future_to_batch = {
            executor.submit(_select_relevant_from_batch, user_query, batch, i): i
            for i, batch in enumerate(batches)
        }

        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_batch):
            batch_idx = future_to_batch[future]
            try:
                selected_ids = future.result()
                all_relevant_ids.update(selected_ids)
            except Exception as e:
                logger.error(f"Batch {batch_idx} raised exception: {e}")
                # On error, include all datasets from that batch
                all_relevant_ids.update(d['id'] for d in batches[batch_idx])

    # Get full dataset objects for relevant IDs
    relevant_datasets = [d for d in useful_datasets if d['id'] in all_relevant_ids]
    logger.info(f"Stage 1 complete: {len(relevant_datasets)}/{len(useful_datasets)} datasets marked as relevant")

    if len(relevant_datasets) == 0:
        logger.warning("No datasets marked as relevant, falling back to top datasets by feature count")
        return sorted(useful_datasets, key=lambda x: x.get('feature_count', 0), reverse=True)[:max_final_datasets]

    # Stage 2: Select the best datasets from relevant ones
    logger.info(f"Stage 2: Selecting top {max_final_datasets} from {len(relevant_datasets)} relevant datasets")
    best_datasets = _select_best_datasets(user_query, relevant_datasets, max_final_datasets)

    logger.info(f"Dataset selection complete: {len(best_datasets)} datasets selected")
    for d in best_datasets:
        logger.info(f"  - {d['title']} ({d.get('feature_count', 0)} features)")

    return best_datasets


def design_index(
    user_query: str,
    available_datasets: List[Dict[str, Any]],
    use_batch_selection: bool = True
) -> Dict[str, Any]:
    """
    AI-driven index design with two-stage dataset selection.

    Stage 1: Parallel batch processing to find ALL relevant datasets
    Stage 2: Select best 10 datasets from relevant ones
    Stage 3: Design the index using selected datasets

    Args:
        user_query: User's question (e.g., "Which district is best for families?")
        available_datasets: List of datasets from IndexCalculator.get_available_datasets()
        use_batch_selection: If True, use two-stage batch selection (default).
                            If False, use all datasets (legacy behavior).

    Returns:
        {
            "name": str,
            "description": str,
            "components": List of component specs,
            "higher_is_better": bool,
            "reasoning": str,
            "selection_info": dict with selection statistics
        }
    """
    llm = ChatOpenAI(model="gpt-5-mini", temperature=0.2)

    # Use two-stage batch selection for better dataset filtering
    if use_batch_selection:
        logger.info(f"design_index: Using two-stage batch selection")
        selected_datasets = select_datasets_for_index(
            user_query=user_query,
            available_datasets=available_datasets,
            batch_size=10,
            max_final_datasets=10
        )
        selection_info = {
            "total_available": len(available_datasets),
            "selected_count": len(selected_datasets),
            "method": "two_stage_batch_selection"
        }
    else:
        # Legacy behavior: use all datasets with features
        selected_datasets = [d for d in available_datasets if d.get('feature_count', 0) > 0]
        selection_info = {
            "total_available": len(available_datasets),
            "selected_count": len(selected_datasets),
            "method": "all_datasets"
        }

    logger.info(f"design_index: {len(selected_datasets)} datasets selected for index design")

    # Format selected datasets with rich details for the final design prompt
    dataset_list = "\n".join([
        f"- {d['title']}\n"
        f"  ID: {d['id']} | Features: {d.get('feature_count', 0)} | District-specific: {'Yes' if d.get('is_district_specific') else 'No'}\n"
        f"  Description: {(d.get('description') or 'No description')[:150]}"
        for d in selected_datasets
    ])

    system_msg = AIMessage(content="""You design composite indices for ranking Munich districts.

TASK: Create an index that answers the user's question by combining 3-10 relevant datasets.

OUTPUT FORMAT (JSON only):
{
    "name": "Index Name",
    "description": "What this index measures",
    "higher_is_better": true,
    "components": [
        {
            "dataset_pattern": "Exact or partial title to match",
            "column": null,
            "weight": 0.25,
            "aggregation": "count",
            "normalize": "population",
            "label": "Human-readable name"
        }
    ],
    "reasoning": "Why these datasets and weights were chosen"
}

RULES:
- dataset_pattern: Use exact title or distinctive substring from the available datasets
- column: null for counting features, or column name for value aggregation (use "Indikatorwert" for indicator datasets)
- weight: -1.0 to 1.0. Negative weights invert the metric (e.g., danger spots reduce family-friendliness)
- aggregation: "count" (count features), "avg" (average values), "sum"
- normalize:
  * "population" - Per 1000 residents. Use for: playgrounds, schools, healthcare, services
  * "area" - Per km². Use for: traffic calming, green spaces, parking
  * "minmax" - Scale 0-100. Use for: pre-calculated indicators (Indikatorwert)

WEIGHT GUIDELINES:
- Core factors: 0.25-0.35
- Secondary factors: 0.15-0.25
- Minor factors: 0.05-0.15
- Weights should sum to approximately 1.0 (absolute values)""")

    user_msg = HumanMessage(content=f"""Design an index for: "{user_query}"

Available datasets:
{dataset_list}

Return ONLY valid JSON.""")

    try:
        response = llm.invoke([system_msg, user_msg])
        content = response.content.strip()

        # Parse JSON
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        result = json.loads(content)

        # Validate required fields
        if "components" not in result or not result["components"]:
            raise ValueError("No components in index design")

        # Ensure defaults
        result.setdefault("name", "Custom Index")
        result.setdefault("description", f"Index based on: {user_query}")
        result.setdefault("higher_is_better", True)
        result.setdefault("reasoning", "AI-designed index")

        # Validate and clean components
        for comp in result["components"]:
            comp.setdefault("column", None)
            comp.setdefault("weight", 0.2)
            comp.setdefault("aggregation", "count")
            comp.setdefault("normalize", "minmax")
            comp.setdefault("label", comp.get("dataset_pattern", "Component"))

        logger.info(f"Designed index '{result.get('name')}' with {len(result['components'])} components:")
        for comp in result["components"]:
            logger.info(f"  - pattern='{comp.get('dataset_pattern')}', weight={comp.get('weight')}")

        # Add selection info to result
        result["selection_info"] = selection_info

        return result

    except Exception as e:
        logger.error(f"Index design failed: {e}")
        return {
            "name": "Custom Index",
            "description": f"Index for: {user_query}",
            "higher_is_better": True,
            "components": [],
            "reasoning": f"Design failed: {str(e)}",
            "error": str(e),
            "selection_info": selection_info
        }


def calculate_index_from_spec(index_spec: Dict[str, Any], db=None) -> Dict[str, Any]:
    """
    Calculate an index from an AI-designed specification.

    Args:
        index_spec: Index design from design_index()
        db: Optional database instance

    Returns:
        Index calculation result from IndexCalculator
    """
    # Import here to avoid circular imports
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from data.indices import IndexComponent, IndexCalculator, NormalizationType

    components = []
    for c in index_spec.get("components", []):
        # Convert normalize string to enum
        norm_str = c.get("normalize", "minmax").lower()
        try:
            norm_type = NormalizationType(norm_str)
        except ValueError:
            norm_type = NormalizationType.MINMAX

        pattern = c.get("dataset_pattern", "")
        logger.info(f"Index component: pattern='{pattern}', weight={c.get('weight')}, normalize={norm_str}")

        components.append(IndexComponent(
            dataset_pattern=pattern,
            column=c.get("column"),
            weight=float(c.get("weight", 0.2)),
            aggregation=c.get("aggregation", "count"),
            normalize=norm_type,
            label=c.get("label", "")
        ))

    if not components:
        return {
            "success": False,
            "error": "No valid components in index specification"
        }

    calculator = IndexCalculator(db)
    result = calculator.calculate_index(
        components=components,
        name=index_spec.get("name", "Custom Index")
    )

    # Log component matching results
    if result.get("success"):
        for comp_info in result.get("components", []):
            logger.info(f"Component '{comp_info.get('label')}': {comp_info.get('districts_with_data')} districts with data, dataset_id={comp_info.get('dataset_id')}")

    return result
