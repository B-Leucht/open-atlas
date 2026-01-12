"""
Composite Index Calculator for Open Atlas
Enables creating district-level indices by combining multiple datasets with weights.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import logging

from .database import Database

logger = logging.getLogger(__name__)


class NormalizationType(Enum):
    """How to normalize values before combining"""
    NONE = "none"           # Raw values
    POPULATION = "population"  # Per capita (per 1000 residents)
    AREA = "area"           # Per km²
    MINMAX = "minmax"       # Scale 0-100
    ZSCORE = "zscore"       # Standard deviations from mean


@dataclass
class IndexComponent:
    """A single component of a composite index"""
    dataset_pattern: str    # Title pattern to match (will resolve to dataset_id)
    column: Optional[str]   # Column to aggregate (None = count)
    weight: float           # Weight in final index (-1 to 1, negative = inverse)
    aggregation: str = "sum"  # count, sum, avg, min, max
    normalize: NormalizationType = NormalizationType.MINMAX
    label: str = ""         # Human-readable label


@dataclass
class IndexPreset:
    """A predefined composite index"""
    id: str
    name: str
    description: str
    icon: str
    components: List[IndexComponent]
    higher_is_better: bool = True


# =============================================================================
# PRESET INDICES
# =============================================================================

CHILD_FRIENDLY_INDEX = IndexPreset(
    id="child-friendly",
    name="Child-Friendly",
    description="How child-friendly is each district based on playgrounds, childcare, safety, and green spaces",
    icon="👶",
    higher_is_better=True,
    components=[
        IndexComponent(
            dataset_pattern="Öffentliche Spielplätze",
            column=None,
            weight=0.25,
            aggregation="count",
            normalize=NormalizationType.POPULATION,
            label="Playgrounds"
        ),
        IndexComponent(
            dataset_pattern="Kindertagesbetreuungseinrichtungen",
            column=None,
            weight=0.25,
            aggregation="count",
            normalize=NormalizationType.POPULATION,
            label="Childcare facilities"
        ),
        IndexComponent(
            dataset_pattern="Tempo-30-Zone",
            column=None,
            weight=0.15,
            aggregation="count",
            normalize=NormalizationType.AREA,
            label="Traffic calming"
        ),
        IndexComponent(
            dataset_pattern="Gefahrenstellen",
            column=None,
            weight=-0.15,
            aggregation="count",
            normalize=NormalizationType.AREA,
            label="Danger spots (inverse)"
        ),
        IndexComponent(
            dataset_pattern="Kinderbetreuung - Betreuungsangebot",
            column="Indikatorwert",
            weight=0.20,
            aggregation="avg",
            normalize=NormalizationType.MINMAX,
            label="Childcare availability"
        ),
    ]
)

SENIOR_FRIENDLY_INDEX = IndexPreset(
    id="senior-friendly",
    name="Senior-Friendly",
    description="How senior-friendly is each district based on healthcare, services, and accessibility",
    icon="👵",
    higher_is_better=True,
    components=[
        IndexComponent(
            dataset_pattern="Alten- und Servicezentrum",
            column=None,
            weight=0.25,
            aggregation="count",
            normalize=NormalizationType.POPULATION,
            label="Senior centers"
        ),
        IndexComponent(
            dataset_pattern="Arzt*Ärztin-Dichte",
            column="Indikatorwert",
            weight=0.25,
            aggregation="avg",
            normalize=NormalizationType.MINMAX,
            label="Doctor density"
        ),
        IndexComponent(
            dataset_pattern="Apotheken-Dichte",
            column="Indikatorwert",
            weight=0.15,
            aggregation="avg",
            normalize=NormalizationType.MINMAX,
            label="Pharmacy density"
        ),
        IndexComponent(
            dataset_pattern="Behindertenparkplätze",
            column=None,
            weight=0.15,
            aggregation="count",
            normalize=NormalizationType.AREA,
            label="Accessible parking"
        ),
        IndexComponent(
            dataset_pattern="Vollstationäre Pflegeeinrichtungen",
            column=None,
            weight=0.20,
            aggregation="count",
            normalize=NormalizationType.POPULATION,
            label="Care facilities"
        ),
    ]
)

SERVICES_INDEX = IndexPreset(
    id="services",
    name="Public Services",
    description="Access to public services and amenities",
    icon="🏛️",
    higher_is_better=True,
    components=[
        IndexComponent(
            dataset_pattern="WLAN-Standorte",
            column=None,
            weight=0.15,
            aggregation="count",
            normalize=NormalizationType.POPULATION,
            label="Public WiFi"
        ),
        IndexComponent(
            dataset_pattern="WC-Standorte",
            column=None,
            weight=0.15,
            aggregation="count",
            normalize=NormalizationType.AREA,
            label="Public toilets"
        ),
        IndexComponent(
            dataset_pattern="Wertstoffinseln",
            column=None,
            weight=0.20,
            aggregation="count",
            normalize=NormalizationType.POPULATION,
            label="Recycling points"
        ),
        IndexComponent(
            dataset_pattern="Nachbarschaftstreffs",
            column=None,
            weight=0.25,
            aggregation="count",
            normalize=NormalizationType.POPULATION,
            label="Community centers"
        ),
        IndexComponent(
            dataset_pattern="Sozialbürgerhaus",
            column=None,
            weight=0.25,
            aggregation="count",
            normalize=NormalizationType.POPULATION,
            label="Social services"
        ),
    ]
)

# All available presets
INDEX_PRESETS = {
    "child-friendly": CHILD_FRIENDLY_INDEX,
    "senior-friendly": SENIOR_FRIENDLY_INDEX,
    "services": SERVICES_INDEX,
}


# =============================================================================
# INDEX CALCULATOR
# =============================================================================

class IndexCalculator:
    """Calculate composite indices from multiple datasets"""

    def __init__(self, db: Database = None):
        self.db = db or Database()
        self._population_cache: Dict[str, float] = {}
        self._area_cache: Dict[str, float] = {}
        self._dataset_id_cache: Dict[str, str] = {}

    def _resolve_dataset_id(self, pattern: str) -> Optional[str]:
        """Resolve a title pattern or dataset ID to an actual dataset ID"""
        if pattern in self._dataset_id_cache:
            return self._dataset_id_cache[pattern]

        with self.db.get_connection() as conn:
            # First try exact ID match (for custom index with dataset IDs)
            cursor = conn.execute(
                "SELECT id FROM datasets WHERE id = ? AND feature_count > 0 LIMIT 1",
                (pattern,)
            )
            row = cursor.fetchone()
            if row:
                self._dataset_id_cache[pattern] = row[0]
                logger.debug(f"Resolved pattern '{pattern}' to dataset ID '{row[0]}' (exact ID match)")
                return row[0]

            # Then try title pattern match (for presets)
            cursor = conn.execute(
                "SELECT id, title FROM datasets WHERE title LIKE ? AND feature_count > 0 LIMIT 1",
                (f"%{pattern}%",)
            )
            row = cursor.fetchone()
            if row:
                self._dataset_id_cache[pattern] = row[0]
                logger.debug(f"Resolved pattern '{pattern}' to dataset ID '{row[0]}' (title: '{row[1]}')")
                return row[0]

            logger.warning(f"Could not resolve pattern '{pattern}' to any dataset")
        return None

    def get_presets(self) -> List[Dict[str, Any]]:
        """Get list of available preset indices"""
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "icon": p.icon,
                "component_count": len(p.components),
                "higher_is_better": p.higher_is_better,
            }
            for p in INDEX_PRESETS.values()
        ]

    def get_preset_details(self, preset_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed info about a preset including its components"""
        preset = INDEX_PRESETS.get(preset_id)
        if not preset:
            return None

        return {
            "id": preset.id,
            "name": preset.name,
            "description": preset.description,
            "icon": preset.icon,
            "higher_is_better": preset.higher_is_better,
            "components": [
                {
                    "dataset_pattern": c.dataset_pattern,
                    "label": c.label,
                    "weight": c.weight,
                    "aggregation": c.aggregation,
                    "normalize": c.normalize.value,
                }
                for c in preset.components
            ]
        }

    def calculate_preset(self, preset_id: str, year: Optional[int] = None) -> Dict[str, Any]:
        """Calculate a preset index"""
        preset = INDEX_PRESETS.get(preset_id)
        if not preset:
            return {"success": False, "error": f"Unknown preset: {preset_id}"}

        return self.calculate_index(preset.components, year, preset.name)

    def calculate_index(
        self,
        components: List[IndexComponent],
        year: Optional[int] = None,
        name: str = "Custom Index"
    ) -> Dict[str, Any]:
        """
        Calculate a composite index from multiple components.

        Returns district scores from 0-100 with per-district component breakdown.
        """
        # Get districts
        districts = self._get_districts()
        if not districts:
            return {"success": False, "error": "No districts found"}

        # Load population and area for normalization
        self._load_normalization_data()

        # Calculate raw values for each component
        component_values: List[Dict[str, float]] = []
        raw_component_values: List[Dict[str, float]] = []  # Pre-normalization values
        successful_components: List[IndexComponent] = []  # Track which components have data
        component_info: List[Dict[str, Any]] = []
        skipped_components: List[Dict[str, Any]] = []

        # Map to store dataset descriptions for breakdown
        component_descriptions: Dict[str, Optional[str]] = {}

        for comp in components:
            dataset_id = self._resolve_dataset_id(comp.dataset_pattern)
            if not dataset_id:
                skipped_components.append({
                    "label": comp.label or comp.dataset_pattern,
                    "reason": "Dataset not found"
                })
                logger.warning(f"Skipping component '{comp.label}': dataset '{comp.dataset_pattern}' not found")
                continue

            # Get dataset description
            description = self._get_dataset_description(dataset_id)

            values = self._calculate_component(comp, districts, year)
            if values:
                component_values.append(values)
                successful_components.append(comp)
                component_descriptions[comp.label or comp.dataset_pattern] = description
                # Store raw values before any district-level normalization was applied
                # Note: _calculate_component already applies normalization, so we need raw counts
                raw_values = self._calculate_raw_component(comp, districts, year)
                raw_component_values.append(raw_values)
                component_info.append({
                    "label": comp.label or comp.dataset_pattern,
                    "weight": comp.weight,
                    "aggregation": comp.aggregation,
                    "normalize": comp.normalize.value if isinstance(comp.normalize, NormalizationType) else comp.normalize,
                    "districts_with_data": len([v for v in values.values() if v > 0]),
                    "dataset_id": dataset_id  # Include dataset ID for fetching features
                })
            else:
                skipped_components.append({
                    "label": comp.label or comp.dataset_pattern,
                    "reason": "No district-level data found"
                })
                logger.warning(f"Skipping component '{comp.label}': no district-level data for dataset '{dataset_id}'")

        if not component_values:
            return {"success": False, "error": "No data available for any component"}

        # Combine components into final scores with breakdown
        final_scores, breakdown = self._combine_components_with_breakdown(successful_components, component_values, raw_component_values, districts, component_descriptions)

        # Build response
        return {
            "success": True,
            "name": name,
            "scores": final_scores,
            "breakdown": breakdown,  # Per-district component values
            "components": component_info,
            "skipped_components": skipped_components,
            "districts": [
                {"number": d["number"], "name": d["name"]}
                for d in districts
            ],
            "stats": {
                "min": min(final_scores.values()) if final_scores else 0,
                "max": max(final_scores.values()) if final_scores else 0,
                "avg": sum(final_scores.values()) / len(final_scores) if final_scores else 0,
            }
        }

    def _get_districts(self) -> List[Dict[str, Any]]:
        """Get all districts"""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT number, name, area_sqm FROM districts ORDER BY CAST(number AS INTEGER)"
            )
            return [
                {"number": row[0], "name": row[1], "area_sqm": row[2]}
                for row in cursor.fetchall()
            ]

    def _load_normalization_data(self):
        """Load population data from Indikatorenatlas"""
        if self._population_cache:
            return

        with self.db.get_connection() as conn:
            # Get population from Bevölkerungsanteil dataset (has absolute numbers in Basiswert.1)
            # Use Raumbezug to extract district number since _district_number may not be set
            cursor = conn.execute("""
                SELECT
                    COALESCE(
                        json_extract(f.properties, '$._district_number'),
                        SUBSTR(json_extract(f.properties, '$.Raumbezug'), 1, 2)
                    ) as district_num,
                    json_extract(f.properties, '$."Basiswert.1"') as population
                FROM features f
                JOIN datasets d ON f.dataset_id = d.id
                WHERE d.title LIKE '%Bevölkerung - Bevölkerungsanteil%'
                AND json_extract(f.properties, '$.Jahr') = '2024'
                AND json_extract(f.properties, '$.Ausprägung') = 'insgesamt'
                AND json_extract(f.properties, '$.Raumbezug') != 'Stadt München'
            """)

            for row in cursor.fetchall():
                if row[0] and row[1]:
                    try:
                        self._population_cache[row[0]] = float(row[1])
                    except (ValueError, TypeError):
                        pass

            logger.info(f"Loaded population data for {len(self._population_cache)} districts, sample: {dict(list(self._population_cache.items())[:3])}")

            # Get area from districts table
            cursor = conn.execute("SELECT number, area_sqm FROM districts")
            for row in cursor.fetchall():
                if row[1]:
                    self._area_cache[row[0]] = row[1] / 1_000_000  # Convert to km²

            logger.info(f"Loaded area data for {len(self._area_cache)} districts, sample: {dict(list(self._area_cache.items())[:3])}")

    def _calculate_raw_component(
        self,
        comp: IndexComponent,
        districts: List[Dict[str, Any]],
        year: Optional[int] = None
    ) -> Dict[str, Dict[str, float]]:
        """Get raw values for a component - returns {district: {count: X, normalized: Y}}"""
        dataset_id = self._resolve_dataset_id(comp.dataset_pattern)
        if not dataset_id:
            return {}

        with self.db.get_connection() as conn:
            if comp.column is None or comp.aggregation == "count":
                # Count features per district - try district_id first, fall back to Raumbezug
                cursor = conn.execute("""
                    SELECT
                        COALESCE(
                            d.number,
                            SUBSTR(json_extract(f.properties, '$.Raumbezug'), 1, 2)
                        ) as district_num,
                        COUNT(f.id) as value
                    FROM features f
                    LEFT JOIN districts d ON f.district_id = d.id
                    WHERE f.dataset_id = ?
                    AND (
                        f.district_id IS NOT NULL
                        OR (json_extract(f.properties, '$.Raumbezug') IS NOT NULL
                            AND json_extract(f.properties, '$.Raumbezug') != 'Stadt München')
                    )
                    GROUP BY district_num
                    HAVING district_num IS NOT NULL AND district_num != ''
                """, (dataset_id,))
            else:
                year_filter = f"AND json_extract(f.properties, '$.Jahr') = '{year}'" if year else ""
                agg_func = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}.get(comp.aggregation, "AVG")
                # Extract district number from Raumbezug (first 2 chars) or _district_number
                cursor = conn.execute(f"""
                    SELECT
                        COALESCE(
                            json_extract(f.properties, '$._district_number'),
                            SUBSTR(json_extract(f.properties, '$.Raumbezug'), 1, 2)
                        ) as district_num,
                        {agg_func}(CAST(json_extract(f.properties, '$."{comp.column}"') AS REAL)) as value
                    FROM features f
                    WHERE f.dataset_id = ? {year_filter}
                    AND (
                        json_extract(f.properties, '$._district_number') IS NOT NULL
                        OR (json_extract(f.properties, '$.Raumbezug') IS NOT NULL
                            AND json_extract(f.properties, '$.Raumbezug') != 'Stadt München')
                    )
                    GROUP BY district_num
                    HAVING district_num IS NOT NULL AND district_num != ''
                """, (dataset_id,))

            raw_counts = {row[0]: float(row[1]) for row in cursor.fetchall() if row[0] and row[1] is not None}

        # Build result with both count and normalized value
        result = {}
        norm_type = comp.normalize if isinstance(comp.normalize, NormalizationType) else NormalizationType(comp.normalize)

        for district_num, count in raw_counts.items():
            normalized = count
            if norm_type == NormalizationType.POPULATION:
                pop = self._population_cache.get(district_num, 0)
                if pop > 0:
                    normalized = (count / pop) * 1000
            elif norm_type == NormalizationType.AREA:
                area = self._area_cache.get(district_num, 0)
                if area > 0:
                    normalized = count / area

            # Include the denominator (population or area) for display
            denominator = None
            if norm_type == NormalizationType.POPULATION:
                denominator = self._population_cache.get(district_num, 0)
            elif norm_type == NormalizationType.AREA:
                denominator = self._area_cache.get(district_num, 0)

            result[district_num] = {"count": count, "normalized": normalized, "denominator": denominator}

        return result

    def _calculate_component(
        self,
        comp: IndexComponent,
        districts: List[Dict[str, Any]],
        year: Optional[int] = None
    ) -> Dict[str, float]:
        """Calculate values for a single component across all districts"""
        # Resolve dataset pattern to ID
        dataset_id = self._resolve_dataset_id(comp.dataset_pattern)
        if not dataset_id:
            logger.warning(f"Could not find dataset matching pattern: '{comp.dataset_pattern}'")
            return {}

        logger.info(f"Calculating component '{comp.label}' using dataset '{dataset_id}'")

        with self.db.get_connection() as conn:
            # Build query based on whether it's a count or value aggregation
            if comp.column is None or comp.aggregation == "count":
                # Count features per district - try district_id first, fall back to Raumbezug
                cursor = conn.execute("""
                    SELECT
                        COALESCE(
                            d.number,
                            SUBSTR(json_extract(f.properties, '$.Raumbezug'), 1, 2)
                        ) as district_num,
                        COUNT(f.id) as value
                    FROM features f
                    LEFT JOIN districts d ON f.district_id = d.id
                    WHERE f.dataset_id = ?
                    AND (
                        f.district_id IS NOT NULL
                        OR (json_extract(f.properties, '$.Raumbezug') IS NOT NULL
                            AND json_extract(f.properties, '$.Raumbezug') != 'Stadt München')
                    )
                    GROUP BY district_num
                    HAVING district_num IS NOT NULL AND district_num != ''
                """, (dataset_id,))
            else:
                # Aggregate a specific column (for Indikatorenatlas data)
                # These use "Raumbezug" field like "01 Altstadt - Lehel" for district
                year_filter = f"AND json_extract(f.properties, '$.Jahr') = '{year}'" if year else ""

                agg_func = {
                    "sum": "SUM",
                    "avg": "AVG",
                    "min": "MIN",
                    "max": "MAX"
                }.get(comp.aggregation, "AVG")

                # Extract district number from Raumbezug (first 2 chars) or _district_number
                cursor = conn.execute(f"""
                    SELECT
                        COALESCE(
                            json_extract(f.properties, '$._district_number'),
                            SUBSTR(json_extract(f.properties, '$.Raumbezug'), 1, 2)
                        ) as district_num,
                        {agg_func}(CAST(json_extract(f.properties, '$."{comp.column}"') AS REAL)) as value
                    FROM features f
                    WHERE f.dataset_id = ?
                    {year_filter}
                    AND (
                        json_extract(f.properties, '$._district_number') IS NOT NULL
                        OR (json_extract(f.properties, '$.Raumbezug') IS NOT NULL
                            AND json_extract(f.properties, '$.Raumbezug') != 'Stadt München')
                    )
                    GROUP BY district_num
                    HAVING district_num IS NOT NULL AND district_num != ''
                """, (dataset_id,))

            raw_values = {}
            for row in cursor.fetchall():
                if row[0] and row[1] is not None:
                    raw_values[row[0]] = float(row[1])

        logger.info(f"Component '{comp.label}': raw values from {len(raw_values)} districts, sample: {dict(list(raw_values.items())[:3])}")

        # Apply normalization
        normalized = self._normalize_values(raw_values, comp.normalize, districts)

        logger.info(f"Component '{comp.label}': after normalization, sample: {dict(list(normalized.items())[:3])}")

        return normalized

    def _normalize_values(
        self,
        values: Dict[str, float],
        norm_type: NormalizationType,
        districts: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Normalize values according to the normalization type"""
        if not values:
            return {}

        if norm_type == NormalizationType.NONE:
            return values

        if norm_type == NormalizationType.POPULATION:
            # Per 1000 residents
            normalized = {}
            for district_num, value in values.items():
                pop = self._population_cache.get(district_num, 0)
                if pop > 0:
                    normalized[district_num] = (value / pop) * 1000
                else:
                    normalized[district_num] = 0
            return normalized

        if norm_type == NormalizationType.AREA:
            # Per km²
            normalized = {}
            for district_num, value in values.items():
                area = self._area_cache.get(district_num, 0)
                if area > 0:
                    normalized[district_num] = value / area
                else:
                    normalized[district_num] = 0
            return normalized

        if norm_type == NormalizationType.MINMAX:
            # Scale to 0-100
            if not values:
                return {}
            min_val = min(values.values())
            max_val = max(values.values())
            if max_val == min_val:
                return {k: 50 for k in values}
            return {
                k: ((v - min_val) / (max_val - min_val)) * 100
                for k, v in values.items()
            }

        if norm_type == NormalizationType.ZSCORE:
            # Standard deviations from mean
            if not values:
                return {}
            mean = sum(values.values()) / len(values)
            std = (sum((v - mean) ** 2 for v in values.values()) / len(values)) ** 0.5
            if std == 0:
                return {k: 0 for k in values}
            return {k: (v - mean) / std for k, v in values.items()}

        return values

    def _get_dataset_description(self, dataset_id: str) -> Optional[str]:
        """Get description for a dataset"""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT description FROM datasets WHERE id = ?",
                (dataset_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def _combine_components_with_breakdown(
        self,
        components: List[IndexComponent],
        component_values: List[Dict[str, float]],
        raw_values: List[Dict[str, float]],
        districts: List[Dict[str, Any]],
        descriptions: Optional[Dict[str, str]] = None
    ) -> Tuple[Dict[str, float], Dict[str, List[Dict[str, Any]]]]:
        """Combine multiple components into a final score with per-district breakdown"""
        district_nums = [d["number"] for d in districts]

        # Normalize all component values to 0-100 scale for fair combination
        normalized_components = []
        for values in component_values:
            # Add missing districts with value 0 so they participate in normalization
            full_values = {dn: values.get(dn, 0) for dn in district_nums}
            if full_values:
                min_val = min(full_values.values())
                max_val = max(full_values.values())
                if max_val > min_val:
                    normalized = {
                        k: ((v - min_val) / (max_val - min_val)) * 100
                        for k, v in full_values.items()
                    }
                else:
                    normalized = {k: 50 for k in full_values}
                normalized_components.append(normalized)
            else:
                normalized_components.append({})

        # Calculate weighted sum with breakdown
        final_scores = {}
        breakdown = {}  # Per-district component breakdown

        for district_num in district_nums:
            score = 0
            weight_sum = 0
            district_breakdown = []

            for i, comp in enumerate(components):
                if i < len(normalized_components):
                    raw_value = normalized_components[i].get(district_num, 0)
                    # Negative weight means inverse (higher raw = lower score)
                    effective_value = 100 - raw_value if comp.weight < 0 else raw_value
                    contribution = effective_value * abs(comp.weight)
                    score += contribution
                    weight_sum += abs(comp.weight)

                    # Get normalization type as string
                    norm_type = comp.normalize.value if isinstance(comp.normalize, NormalizationType) else comp.normalize

                    # Get the raw values for this district
                    raw_data = raw_values[i].get(district_num, {}) if i < len(raw_values) else {}
                    raw_count = raw_data.get("count", 0)
                    raw_denominator = raw_data.get("denominator")

                    label = comp.label or comp.dataset_pattern
                    district_breakdown.append({
                        "label": label,
                        "description": descriptions.get(label) if descriptions else None,
                        "value": round(raw_value, 1),
                        "count": round(raw_count),
                        "denominator": round(raw_denominator, 1) if raw_denominator else None,
                        "weight": comp.weight,
                        "contribution": round(contribution, 1),
                        "normalize": norm_type,
                        "aggregation": comp.aggregation
                    })

            if weight_sum > 0:
                final_scores[district_num] = score / weight_sum
            else:
                final_scores[district_num] = 0

            breakdown[district_num] = district_breakdown

        return final_scores, breakdown

    def get_available_datasets(self) -> List[Dict[str, Any]]:
        """Get datasets that can be used in custom indices"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT id, title, feature_count, is_district_specific, has_geometry, description
                FROM datasets
                WHERE feature_count > 0
                ORDER BY
                    CASE WHEN title LIKE '%Indikatorenatlas%' THEN 0 ELSE 1 END,
                    title
            """)

            return [
                {
                    "id": row[0],
                    "title": row[1],
                    "feature_count": row[2],
                    "is_district_specific": bool(row[3]),
                    "has_geometry": bool(row[4]),
                    "description": row[5],
                }
                for row in cursor.fetchall()
            ]
