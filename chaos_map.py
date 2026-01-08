#!/usr/bin/env python3
"""
OpenData Munich Chaos Map Generator
Generates a visualization of ALL data from the Open Atlas database.
"""

import argparse
import json
import math
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection
import numpy as np

# Database path
DB_PATH = Path(__file__).parent / "backend" / "data" / "openatlas.db"

# Munich coordinate bounds
MUNICH_WGS84 = {'min_lon': 11.35, 'max_lon': 11.80, 'min_lat': 48.02, 'max_lat': 48.28}
MUNICH_UTM = {'min_x': 680000, 'max_x': 700000, 'min_y': 5320000, 'max_y': 5350000}


def is_utm(x, y):
    """Check if coordinates are UTM Zone 32N"""
    return (MUNICH_UTM['min_x'] < x < MUNICH_UTM['max_x'] and
            MUNICH_UTM['min_y'] < y < MUNICH_UTM['max_y'])


def is_wgs84(lon, lat):
    """Check if coordinates are valid WGS84 for Munich"""
    return (MUNICH_WGS84['min_lon'] <= lon <= MUNICH_WGS84['max_lon'] and
            MUNICH_WGS84['min_lat'] <= lat <= MUNICH_WGS84['max_lat'])


def point_in_polygon(x, y, polygon_coords):
    """Ray casting algorithm to check if point is inside polygon"""
    n = len(polygon_coords)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon_coords[i][0], polygon_coords[i][1]
        xj, yj = polygon_coords[j][0], polygon_coords[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def get_district_polygon(geometry_json):
    """Extract the main polygon coordinates from district geometry"""
    if not geometry_json:
        return None
    geom = json.loads(geometry_json) if isinstance(geometry_json, str) else geometry_json
    geom_type = geom.get('type', '')
    coords = geom.get('coordinates', [])

    if geom_type == 'Polygon' and coords:
        return coords[0]  # exterior ring
    elif geom_type == 'MultiPolygon' and coords:
        # Return the largest polygon (by number of points)
        largest = max(coords, key=lambda p: len(p[0]) if p else 0)
        return largest[0] if largest else None
    return None


def jitter_point_in_district(centroid_lon, centroid_lat, polygon_coords, area_sqm, max_attempts=15):
    """Generate a jittered point that stays inside the district polygon"""
    if not polygon_coords:
        return centroid_lon, centroid_lat

    area_factor = math.sqrt(area_sqm / 1e6) if area_sqm else 0.01

    for attempt in range(max_attempts):
        # Reduce jitter on each attempt to ensure convergence
        scale = 1.0 - (attempt * 0.05)
        jitter_lon = random.gauss(0, area_factor * 0.010 * scale)
        jitter_lat = random.gauss(0, area_factor * 0.008 * scale)

        new_lon = centroid_lon + jitter_lon
        new_lat = centroid_lat + jitter_lat

        if point_in_polygon(new_lon, new_lat, polygon_coords):
            return new_lon, new_lat

    # Fallback: return centroid with tiny jitter (centroid should always be inside)
    return centroid_lon + random.uniform(-0.0005, 0.0005), centroid_lat + random.uniform(-0.0005, 0.0005)


def utm32n_to_wgs84(x, y):
    """Convert UTM Zone 32N to WGS84"""
    try:
        k0, a, e = 0.9996, 6378137.0, 0.0818192
        e2 = e * e
        x = x - 500000
        M = y / k0
        mu = M / (a * (1 - e2/4 - 3*e2*e2/64))
        e1 = (1 - math.sqrt(1-e2)) / (1 + math.sqrt(1-e2))
        phi1 = mu + (3*e1/2 - 27*e1**3/32) * math.sin(2*mu)
        phi1 += (21*e1**2/16 - 55*e1**4/32) * math.sin(4*mu)
        phi1 += (151*e1**3/96) * math.sin(6*mu)
        N1 = a / math.sqrt(1 - e2 * math.sin(phi1)**2)
        T1 = math.tan(phi1)**2
        R1 = a * (1-e2) / (1 - e2*math.sin(phi1)**2)**1.5
        D = x / (N1 * k0)
        lat = phi1 - (N1 * math.tan(phi1) / R1) * (D**2/2 - (5 + 3*T1) * D**4/24)
        lon = (D - (1 + 2*T1) * D**3/6) / math.cos(phi1)
        return math.degrees(lon) + 9, math.degrees(lat)
    except:
        return None, None


def convert_coord(x, y):
    """Convert coordinate to WGS84 if needed"""
    if is_wgs84(x, y):
        return x, y
    if is_utm(x, y):
        return utm32n_to_wgs84(x, y)
    return None, None


def extract_coords_recursive(coords):
    """Recursively extract all coordinate pairs from nested arrays"""
    results = []
    if not coords:
        return results
    if isinstance(coords[0], (int, float)) and len(coords) >= 2:
        lon, lat = convert_coord(coords[0], coords[1])
        if lon and lat:
            results.append((lon, lat))
    elif isinstance(coords[0], list):
        for c in coords:
            results.extend(extract_coords_recursive(c))
    return results


def generate_chaos_map(db_path: str = None, output_path: str = "munich_chaos_map.png",
                       dpi: int = 200, figsize: tuple = (40, 36)):
    """Generate the ultimate chaos map with ALL data"""

    db_path = db_path or str(DB_PATH)
    if not Path(db_path).exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("Loading data from database...")

    # Get districts and pre-compute polygons
    cursor.execute("SELECT number, name, centroid_lat, centroid_lon, geometry, area_sqm FROM districts")
    districts = {}
    for row in cursor.fetchall():
        d = dict(row)
        d['polygon'] = get_district_polygon(d['geometry'])
        districts[row['number']] = d
    print(f"  Districts: {len(districts)}")

    # Get all features
    cursor.execute("""
        SELECT f.id, f.geometry, f.properties, d.title as dataset_title, d.is_district_specific
        FROM features f
        JOIN datasets d ON f.dataset_id = d.id
    """)
    all_features = cursor.fetchall()
    print(f"  Features: {len(all_features):,}")

    # Create figure
    print(f"\nGenerating chaos map ({figsize[0]}x{figsize[1]} @ {dpi} DPI)...")
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_facecolor('#030308')
    fig.patch.set_facecolor('#010103')

    # Color palette
    np.random.seed(42)
    colors = np.vstack([
        plt.cm.rainbow(np.linspace(0, 1, 40)),
        plt.cm.viridis(np.linspace(0, 1, 30)),
        plt.cm.plasma(np.linspace(0, 1, 30)),
    ])
    dataset_colors = {}
    color_idx = 0

    all_points = []
    all_lines = []
    all_line_colors = []
    dataset_counts = defaultdict(int)

    print("Processing features...")
    random.seed(42)

    for i, row in enumerate(all_features):
        if i % 50000 == 0 and i > 0:
            print(f"  {i:,}/{len(all_features):,}...")

        dataset = row['dataset_title'] or 'Unknown'
        if dataset not in dataset_colors:
            dataset_colors[dataset] = colors[color_idx % len(colors)]
            color_idx += 1
        color = dataset_colors[dataset]

        properties = json.loads(row['properties']) if row['properties'] else {}
        geometry = json.loads(row['geometry']) if row['geometry'] else None

        point_added = False

        # Process geometry
        if geometry:
            coords = geometry.get('coordinates', [])
            pts = extract_coords_recursive(coords)

            if pts:
                # Add lines between consecutive points
                if len(pts) >= 2:
                    for j in range(len(pts) - 1):
                        all_lines.append([pts[j], pts[j+1]])
                        all_line_colors.append(color)

                # Add centroid as point
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                all_points.append((cx, cy, color))
                point_added = True

        # District-specific data without geometry - place at district centroid with jitter
        if not point_added and row['is_district_specific']:
            district_num = None
            raumbezug = properties.get('Raumbezug', '')
            if raumbezug and raumbezug != 'Stadt München' and len(raumbezug) >= 2:
                district_num = raumbezug[:2] if raumbezug[:2].isdigit() else None

            if not district_num:
                district_num = properties.get('_district_number') or properties.get('sb_nummer')

            if district_num and district_num in districts:
                d = districts[district_num]
                if d['centroid_lat'] and d['centroid_lon']:
                    # Use polygon-constrained jitter
                    lon, lat = jitter_point_in_district(
                        d['centroid_lon'], d['centroid_lat'],
                        d['polygon'], d['area_sqm']
                    )
                    if is_wgs84(lon, lat):
                        all_points.append((lon, lat, color))
                        point_added = True

        if point_added:
            dataset_counts[dataset] += 1

    print(f"\nPlotting:")
    print(f"  Points: {len(all_points):,}")
    print(f"  Lines: {len(all_lines):,}")
    print(f"  Datasets: {len(dataset_counts)}")

    # Draw district boundaries
    print("Drawing districts...")
    for num, d in districts.items():
        if d['geometry']:
            geom = json.loads(d['geometry'])
            coords = geom.get('coordinates', [])
            if geom['type'] == 'MultiPolygon':
                for polygon in coords:
                    if polygon:
                        exterior = polygon[0]
                        xs = [c[0] for c in exterior]
                        ys = [c[1] for c in exterior]
                        ax.fill(xs, ys, alpha=0.02, color='cyan')
                        ax.plot(xs, ys, '-', color='#00ffff', linewidth=2, alpha=0.3)
                        ax.plot(xs, ys, '-', color='#ffffff', linewidth=0.5, alpha=0.7)

    # Draw lines
    print("Drawing lines...")
    if all_lines:
        lc = LineCollection(all_lines, colors=all_line_colors, linewidths=0.08, alpha=0.35)
        ax.add_collection(lc)

    # Draw points
    print("Drawing points...")
    if all_points:
        xs = [p[0] for p in all_points]
        ys = [p[1] for p in all_points]
        cs = [p[2] for p in all_points]
        ax.scatter(xs, ys, s=1, c=cs, alpha=0.2, marker='o')
        ax.scatter(xs, ys, s=0.2, c=cs, alpha=0.6, marker='.')

    # District labels
    for num, d in districts.items():
        if d['centroid_lat'] and d['centroid_lon']:
            ax.annotate(num, (d['centroid_lon'], d['centroid_lat']),
                fontsize=18, ha='center', va='center', fontweight='bold', color='#00ffff',
                bbox=dict(boxstyle='circle,pad=0.3', facecolor='#000000', alpha=0.9,
                         edgecolor='#00ffff', linewidth=2))

    ax.set_xlim(MUNICH_WGS84['min_lon'], MUNICH_WGS84['max_lon'])
    ax.set_ylim(MUNICH_WGS84['min_lat'], MUNICH_WGS84['max_lat'])

    ax.set_title(
        f'MUNICH CHAOS MAP\n{len(all_points):,} Points | {len(all_lines):,} Lines | {len(dataset_counts)} Datasets | {len(all_features):,} Features',
        color='#00ffff', fontsize=28, fontweight='bold', pad=25)

    ax.tick_params(colors='#666666', labelsize=12)
    for spine in ax.spines.values():
        spine.set_color('#333333')

    # Legend
    top_datasets = sorted(dataset_counts.items(), key=lambda x: x[1], reverse=True)[:30]
    legend_patches = [mpatches.Patch(color=dataset_colors.get(ds[0], 'gray'),
                       label=f"{ds[0][:45]} ({ds[1]:,})") for ds in top_datasets]
    legend = ax.legend(handles=legend_patches, loc='upper left', fontsize=6,
                       title='TOP 30 DATASETS', facecolor='#050510', edgecolor='#333333', title_fontsize=9)
    legend.get_title().set_color('#00ffff')
    for text in legend.get_texts():
        text.set_color('#cccccc')

    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, facecolor=fig.get_facecolor(), bbox_inches='tight')
    print(f"\nSaved: {output_path}")

    conn.close()
    return len(all_points), len(all_lines), len(dataset_counts)


def main():
    parser = argparse.ArgumentParser(
        description="Generate Munich Open Data chaos map visualization"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="munich_chaos_map.png",
        help="Output file path (default: munich_chaos_map.png)"
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Output DPI (default: 200)"
    )
    parser.add_argument(
        "--width",
        type=int,
        default=40,
        help="Figure width in inches (default: 40)"
    )
    parser.add_argument(
        "--height",
        type=int,
        default=36,
        help="Figure height in inches (default: 36)"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to database file (default: backend/data/openatlas.db)"
    )

    args = parser.parse_args()

    try:
        points, lines, datasets = generate_chaos_map(
            db_path=args.db,
            output_path=args.output,
            dpi=args.dpi,
            figsize=(args.width, args.height)
        )
        print(f"\nChaos map complete: {points:,} points, {lines:,} lines, {datasets} datasets")
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)


if __name__ == "__main__":
    main()
