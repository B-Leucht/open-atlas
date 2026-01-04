# Open Data Munich - Comprehensive Dataset Analysis & App Enhancement Plan

## Executive Summary

After analyzing all **339 datasets** from Open Data Munich, I've categorized them by usefulness for the map application and developed a vision for transforming the app into an **Insights Platform** that enables powerful composite visualizations like "bike-friendliness" or "child-friendliness" indices.

---

## Dataset Overview

| Category | Count | Description |
|----------|-------|-------------|
| **Total Datasets** | 339 | All datasets in Open Data Munich |
| **With Geometry** | 87 (26%) | Directly mappable |
| **District-Specific** | 22 (6%) | Have district column, can be choropleth visualized |
| **Synced Features** | 119,765 | Total features in database |

---

## Dataset Categories & Recommendations

### TIER 1: High-Value Geo-Located Datasets (KEEP - Core Map Data)

These datasets have coordinates and are essential for map visualizations:

#### Mobility & Traffic (Most Valuable)
| Dataset | Features | Use Case |
|---------|----------|----------|
| Radverkehrsanlagen (Bike Infrastructure) | 21,172 | Bike paths, lanes - core for bike-friendliness |
| Straßennetzgraf (Street Network) | 22,433 | Road network analysis |
| Radlstadtplan - Radwege | 6,553 | Dedicated bike paths |
| Radlstadtplan - Gemeinsame Rad/Fußwege | 6,553 | Shared paths |
| Radlstadtplan - Tempo-30-Zone | 1,118 | Traffic calming zones |
| Fahrradparken mit Standardmaßen | 3,574 | Bike parking locations |
| Fahrradstraßen | 121 | Bike priority streets |
| Radentscheidmaßnahmen | 1,421 | Planned bike improvements |
| Überhol-/Seitenabstandsdaten | 5,337 | Overtaking safety data |
| Parkseiten | 12,878 | Parking regulations |
| Ladeinfrastruktur | 370 | EV charging |
| Carsharing Parkplätze | 819 | Car sharing stations |
| Mikromobilitäts-Abstellflächen | 354 | E-scooter zones |

#### Safety & Accessibility
| Dataset | Features | Use Case |
|---------|----------|----------|
| Gefahrenstellen | 142 | Dangerous locations |
| Blindenleitsystem | 51 | Accessibility features |
| Behindertenparkplätze | 559 | Accessible parking |
| Baustellen | 3,459 | Current construction |

#### Public Spaces & Recreation
| Dataset | Features | Use Case |
|---------|----------|----------|
| Öffentliche Spielplätze | 824 | Playgrounds |
| Baden in der Isar | 3,110 | Swimming spots |
| Schwimmbäder | 15 | Public pools |
| Hallensportprogramm | 121 | Sports facilities |
| Trinkbrunnen | 98 | Drinking fountains |
| Points of Interest Isar | 44 | Recreation spots |

#### Services & Facilities
| Dataset | Features | Use Case |
|---------|----------|----------|
| Wertstoffinseln | 859 | Recycling stations |
| Wertstoffhöfe | 12 | Recycling centers |
| WC-Standorte | 296 | Public toilets |
| WLAN-Standorte | 421 | Public WiFi |
| Märkte | 54 | Markets |
| Alten-/Servicezentren | 33 | Senior services |
| Sozialbürgerhaus | 12 | Social services |
| Nachbarschaftstreffs | 55 | Community centers |
| Stadtbibliothek | 26 | Libraries |

#### Boundaries & Administrative
| Dataset | Features | Use Case |
|---------|----------|----------|
| Stadtbezirke | 27 | District boundaries |
| Bezirksteile | 110 | Sub-district boundaries |
| Stadtviertel | 477 | Neighborhood boundaries |
| Kehrbezirke | 175 | Chimney sweep districts |

---

### TIER 2: Indikatorenatlas (CRITICAL - Statistical Indicators)

**68 datasets** with uniform structure containing time-series district-level statistics. These are the key to composite indices!

#### Structure
```csv
"Indikator","Ausprägung","Jahr","Raumbezug","Indikatorwert","Basiswert.1","Basiswert.2"...
"Bevölkerungsanteil","insgesamt",2024,"01 Altstadt - Lehel",1.3,20876,1603776,...
```

#### Categories & Indicators

**Demographics (Bevölkerung)**
- Bevölkerungsanteil (population share)
- Bevölkerungsdichte (density)
- Durchschnittsalter (average age)
- Altersgruppen (age distribution)
- Jugendquotient (youth ratio)
- Altenquotient (elderly ratio)
- Migrationshintergrund (migration background)
- Einpersonenhaushalte (single households)
- Haushalte mit Kindern (families with children)
- Geburtenrate (birth rate)
- Wohndauer (residence duration)

**Child & Family Indicators**
- Kinderbetreuung - Betreuungsangebot (childcare availability)
- Kinderbetreuung - Altersgruppen (childcare by age)
- Grundschüler - Staatsangehörigkeit
- Grundschüler - Familiensprache
- Migrationshintergrund Kinder

**Health**
- Apotheken-Dichte (pharmacy density)
- Arzt-Dichte (doctor density)
- Psychotherapeut-Dichte
- Zahnarzt-Dichte

**Economy & Employment**
- Arbeitslose/Arbeitslosen-Anteil (unemployment)
- Sozialversicherungspflichtig Beschäftigte
- Leistungsberechtigte (welfare recipients)

**Traffic & Mobility**
- Motorisierungsgrad PKW (car ownership)
- Erstzulassungsanteil PKW (new car registrations)

**Building & Housing**
- Baufertigstellungen (building completions)
- Baugenehmigungen (building permits)
- Flächennutzung (land use)

---

### TIER 3: Non-Geo District Data (KEEP - For Aggregation)

These don't have coordinates but have district information:

| Dataset | Records | Value |
|---------|---------|-------|
| Kindertagesbetreuungseinrichtungen | 1,589 | Has coordinates + district - childcare locations |
| Bevölkerung Stadtbezirksteile | 108 | Population by sub-district |
| Wahlräume | 509+ | Voting locations |

---

### TIER 4: Time-Series Data (KEEP - For Trends)

These are valuable for temporal analysis even without location:

| Dataset | Description |
|---------|-------------|
| Raddauerzählstellen (2017-2025) | ~71 monthly datasets of bike traffic counts |
| Bibliothekskennzahlen | Library usage statistics |
| Daten Tierpark Hellabrunn | Zoo statistics |
| MVG-Rad Fahrten | Bike-share trips |
| Die Bevölkerung seit 1900 | Historical population |

---

### TIER 5: Low-Priority Datasets (Consider Removing)

Datasets with limited map utility:

| Reason | Examples |
|--------|----------|
| Meta/administrative | Datensätze des Open Data Portals (meta), Fernzugriffsberechtigungen |
| Non-spatial analysis | Cycling in Munich Analysis, Dynamik des Drahtesels |
| Historical elections | Wahlergebnisse (useful for district view but static) |
| Budget data | Ergebnishaushalt (no spatial component) |
| Events | Bisherige Veranstaltungen Messe München |

---

## App Enhancement Vision

### 1. Composite Index Builder

The most valuable enhancement would be a **Composite Index Builder** that allows users to create custom district-level scores by combining multiple datasets:

#### Example: "Bike-Friendliness Index"
Combine with configurable weights:
- (+) Bike infrastructure density (Radverkehrsanlagen per km²)
- (+) Bike parking per capita (Fahrradparken / population)
- (+) Tempo-30 zones coverage (%)
- (+) Fahrradstraßen length
- (-) Car ownership rate (Motorisierungsgrad)
- (-) Dangerous locations (Gefahrenstellen)
- (+) Bike service stations density

#### Example: "Child-Friendliness Index"
- (+) Playgrounds per 1000 children
- (+) Kindergarten capacity / child population
- (+) Tempo-30 zone coverage
- (+) Parks and green spaces
- (+) Schools per district
- (-) Traffic density
- (-) Dangerous locations
- (+) Youth facilities

#### Example: "Senior-Friendliness Index"
- (+) Alten-/Servicezentren density
- (+) Pharmacy density
- (+) Doctor density
- (+) Public transport accessibility
- (+) Barrier-free infrastructure
- (-) Dangerous locations

### 2. Per-Capita Normalizations

Automatically offer per-capita views:
- Bike parking spots per 1,000 residents
- Playgrounds per 1,000 children
- Doctors per 10,000 residents
- Charging stations per 1,000 cars

### 3. Time-Series Visualization

For Indikatorenatlas data:
- Show change over time (2015-2024 trends)
- Highlight improving/declining districts
- Compare "before/after" for any indicator

### 4. Overlap/Intersection Analysis

- "Show areas with BOTH playgrounds AND Tempo-30 zones"
- "Districts with high childcare AND low car ownership"
- Buffer analysis: "How many playgrounds within 500m of bike paths?"

---

## Proposed UI Changes

### A. Enhanced District View Panel

```
┌─────────────────────────────────────────────────────┐
│  DISTRICT INSIGHTS                              ✕  │
├─────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────┐   │
│  │ Quick Views                                 │   │
│  │  🚴 Bike-Friendly  👶 Child-Friendly       │   │
│  │  👵 Senior-Friendly  🌳 Green Spaces       │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ── OR BUILD CUSTOM INDEX ──                       │
│                                                     │
│  Add Indicators:                                   │
│  ┌─────────────────────────────────────────────┐   │
│  │ [Search indicators...]                      │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  Selected Indicators:                              │
│  ┌─────────────────────────────────────────────┐   │
│  │ + Bike Infrastructure    Weight: ████░ 80%  │   │
│  │ + Playgrounds/1000       Weight: ███░░ 60%  │   │
│  │ - Car Ownership          Weight: ██░░░ 40%  │   │
│  │                                    [+ Add]  │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  Normalize by:                                     │
│  ○ None  ● Population  ○ Area  ○ Children         │
│                                                     │
│  [     Generate Index Map     ]                    │
└─────────────────────────────────────────────────────┘
```

### B. Indikatorenatlas Browser

```
┌─────────────────────────────────────────────────────┐
│  INDICATOR ATLAS                                ✕  │
├─────────────────────────────────────────────────────┤
│  Category: [Bevölkerung ▼]                         │
│                                                     │
│  Indicators:                                       │
│  ├── Bevölkerungsdichte                           │
│  ├── Durchschnittsalter                           │
│  ├── Migrationshintergrund                        │
│  └── Jugendquotient                               │
│                                                     │
│  Year: [2024 ▼]  ──●────────  2015 ◄──► 2024      │
│                                                     │
│  Dimension: [insgesamt ▼]                          │
│             ○ männlich  ○ weiblich                 │
│                                                     │
│  [Show on Map]  [Compare Years]  [Export]          │
└─────────────────────────────────────────────────────┘
```

### C. Layer Overlap Mode

```
┌─────────────────────────────────────────────────────┐
│  SPATIAL ANALYSIS                               ✕  │
├─────────────────────────────────────────────────────┤
│  Layer A: [Spielplätze ▼]                          │
│  Layer B: [Tempo-30-Zonen ▼]                       │
│                                                     │
│  Analysis Type:                                    │
│  ○ Intersection (A ∩ B)                            │
│  ● Buffer (within distance)                        │
│  ○ Contains                                        │
│                                                     │
│  Buffer Distance: [500] meters                     │
│                                                     │
│  [Run Analysis]                                    │
│                                                     │
│  Results: 724 playgrounds within 500m of          │
│           traffic-calmed zones                     │
└─────────────────────────────────────────────────────┘
```

---

## Technical Implementation Requirements

### Backend Changes

1. **New Ingestion for Indikatorenatlas**
   - Parse the CSV structure with Raumbezug → district mapping
   - Store year, Ausprägung (dimension), indicator name
   - Enable time-series queries

2. **Composite Index API**
   ```python
   POST /api/composite-index
   {
     "name": "bike-friendliness",
     "indicators": [
       {"dataset": "fahrradparken", "weight": 0.3, "normalize": "population"},
       {"dataset": "radverkehrsanlagen", "weight": 0.4, "normalize": "area"},
       {"indicator": "motorisierungsgrad", "weight": -0.3}
     ]
   }
   ```

3. **Per-Capita Normalization**
   - Join with population data
   - Support: per capita, per km², per 1000 children, etc.

4. **Spatial Analysis API**
   - Buffer queries
   - Intersection counts
   - Distance calculations

### Frontend Changes

1. **Composite Index Builder Component**
   - Drag-and-drop indicator selection
   - Weight sliders
   - Normalization dropdown

2. **Indikatorenatlas Browser**
   - Hierarchical category navigation
   - Year slider with animation
   - Dimension toggle (total/male/female)

3. **Comparison View**
   - Side-by-side district comparison
   - Time-series charts
   - Ranking tables

4. **Preset Indices**
   - Pre-configured indices for common use cases
   - One-click activation

---

---

## CRITICAL BUG: Indikatorenatlas Not Being Ingested

### Root Cause Analysis

The Indikatorenatlas datasets show 0 features because of **two issues**:

#### Issue 1: Missing District Column Pattern

In `backend/data/sync.py` line 25-28, the `DISTRICT_COLUMN_PATTERNS` list doesn't include "raumbezug":

```python
DISTRICT_COLUMN_PATTERNS = [
    'sb_nummer', 'stadtbezirk', 'bezirk', 'bezirksnummer', 'district',
    'stadtbezirk_nr', 'bezirks_nr', 'sbz', 'stadtteil'
]
```

**Fix**: Add `'raumbezug'` to this list.

#### Issue 2: CSV Parser District Detection

In `backend/data/parsers.py` line 193, the `CSVParser.DISTRICT_PATTERNS` also misses "raumbezug":

```python
DISTRICT_PATTERNS = ['sb_nummer', 'stadtbezirk', 'bezirk', 'bezirksnummer', 'district']
```

**Fix**: Add `'raumbezug'` to this list.

#### Issue 3: District Value Format

The Indikatorenatlas uses a combined format for districts:
```
"Raumbezug": "01 Altstadt - Lehel"
```

This needs parsing to extract:
- District number: `01`
- District name: `Altstadt - Lehel`

**Fix**: Add a parsing function to extract district number from the Raumbezug format.

### Recommended Code Changes

```python
# In parsers.py - add to CSVParser.DISTRICT_PATTERNS
DISTRICT_PATTERNS = [
    'sb_nummer', 'stadtbezirk', 'bezirk', 'bezirksnummer', 'district',
    'raumbezug'  # <-- ADD THIS
]

# In sync.py - add to DISTRICT_COLUMN_PATTERNS
DISTRICT_COLUMN_PATTERNS = [
    'sb_nummer', 'stadtbezirk', 'bezirk', 'bezirksnummer', 'district',
    'stadtbezirk_nr', 'bezirks_nr', 'sbz', 'stadtteil',
    'raumbezug'  # <-- ADD THIS
]

# Add helper function to parse Raumbezug format
def parse_raumbezug(value: str) -> Optional[str]:
    """
    Parse Indikatorenatlas Raumbezug format to district number.
    Examples:
    - "01 Altstadt - Lehel" -> "01"
    - "Stadt München" -> None (city-wide)
    """
    if not value or value.startswith('Stadt'):
        return None
    parts = value.strip().split(' ', 1)
    if parts and parts[0].isdigit():
        return parts[0].zfill(2)
    return None
```

### Indikatorenatlas Data Model

These datasets need a **special data model** because they're time-series statistical data:

```python
@dataclass
class Indicator:
    """A single indicator value"""
    indicator_name: str       # "Bevölkerungsanteil"
    dimension: str            # "insgesamt", "männlich", "weiblich"
    year: int                 # 2024
    district_number: str      # "01"
    value: float              # 1.3
    base_values: Dict[str, float]  # Basiswert.1 -> 20876, etc.
    base_names: Dict[str, str]     # Name.Basiswert.1 -> "Hauptwohnsitzbevölkerung"
```

---

## Implementation Priority

### Phase 1: Foundation (Essential)
1. **FIX Indikatorenatlas ingestion** (add 'raumbezug' to patterns, parse format)
2. Create indicator-specific data model
3. Add population normalization to existing district view

### Phase 2: Core Features
1. Composite Index Builder (basic version)
2. Pre-built indices (bike-friendly, child-friendly)
3. Per-capita toggle in UI

### Phase 3: Advanced Analytics
1. Time-series visualization
2. Trend analysis
3. Comparison mode

### Phase 4: Spatial Analysis
1. Buffer analysis
2. Layer intersection
3. Custom area selection

---

## Datasets to Remove (Optional)

Low-value datasets that add noise:
- Meta datasets about the portal itself
- Analysis reports (PDFs, studies)
- Datasets with no useful structure

---

## Conclusion

The app already has excellent infrastructure for map visualization. The main opportunity is to:

1. **Fix Indikatorenatlas ingestion** - these 68 datasets are goldmines of district-level statistics
2. **Add composite index builder** - enable powerful multi-factor analysis
3. **Support per-capita normalization** - make numbers meaningful
4. **Create preset indices** - make complex analysis accessible

This would transform the app from a data browser into an **insights platform** for understanding Munich's neighborhoods.
