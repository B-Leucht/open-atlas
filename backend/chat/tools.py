"""
Analysis Tools for Munich Open Data
DuckDB-based CSV and geospatial data analysis
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


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
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)

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

        return {
            "kind": "csv",
            "sql_query": sql_query,
            "preview_markdown": result_df.head(200).to_markdown(index=False),
            "columns": list(result_df.columns),
            "row_count": len(result_df),
        }

    finally:
        conn.close()


def analyze_geospatial(url: str, user_query: str) -> Dict[str, Any]:
    """
    Analyze geospatial data with DuckDB spatial extension.
    Loads GeoJSON/WFS, generates and executes spatial SQL.
    """
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
        preview_md = preview_df.head(20).to_markdown(index=False)

        # Generate SQL
        sql_query = generate_sql(user_query, columns, preview_md, "geo", spatial=True)

        # Execute query
        try:
            result_df = conn.execute(sql_query).fetch_df()
        except Exception as e:
            logger.debug(f"Spatial SQL failed, using fallback: {e}")
            result_df = preview_df
            sql_query = "SELECT * FROM geo LIMIT 200"

        # Extract coordinates if present
        coords = None
        lat_cols = [c for c in result_df.columns if c.lower() in ("lat", "latitude", "y")]
        lon_cols = [c for c in result_df.columns if c.lower() in ("lon", "longitude", "x")]
        if lat_cols and lon_cols:
            coords = result_df[[lat_cols[0], lon_cols[0]]].head(100).to_dict(orient="records")

        result = {
            "kind": "geospatial",
            "sql_query": sql_query,
            "preview_markdown": result_df.head(200).to_markdown(index=False),
            "columns": list(result_df.columns),
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
