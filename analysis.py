#!/usr/bin/env python3
"""
Munich Open Data Analysis
Generates visualizations and statistics about the Open Atlas database.
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

DB_PATH = Path(__file__).parent / "backend" / "data" / "openatlas.db"

COLORS = [
    '#00d4ff', '#ff006e', '#ffbe0b', '#8338ec', '#3a86ff', '#00f5d4',
    '#fb5607', '#ff0054', '#9b5de5', '#00ff87', '#f15bb5', '#fee440'
]


def get_db_connection(db_path: str = None):
    """Get database connection"""
    path = db_path or str(DB_PATH)
    if not Path(path).exists():
        print(f"Error: Database not found: {path}", file=sys.stderr)
        sys.exit(1)
    return sqlite3.connect(path)


def print_statistics(db_path: str = None):
    """Print detailed statistics about the database"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    print("=" * 70)
    print("MUNICH OPEN DATA - DATABASE ANALYSIS")
    print("=" * 70)

    # Basic counts
    cursor.execute("SELECT COUNT(*) FROM datasets")
    total_datasets = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM features")
    total_features = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM districts")
    total_districts = cursor.fetchone()[0]

    print(f"\n{'OVERVIEW':^70}")
    print("-" * 70)
    print(f"  Datasets:     {total_datasets:>10,}")
    print(f"  Features:     {total_features:>10,}")
    print(f"  Districts:    {total_districts:>10}")

    # Geo stats
    cursor.execute("SELECT COUNT(*) FROM features WHERE geometry IS NOT NULL")
    with_geo = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM features WHERE district_id IS NOT NULL")
    with_district = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM features WHERE centroid_lat BETWEEN 48 AND 49")
    valid_centroids = cursor.fetchone()[0]

    print(f"\n{'GEO COVERAGE':^70}")
    print("-" * 70)
    print(f"  With geometry:        {with_geo:>10,} ({with_geo/total_features*100:.1f}%)")
    print(f"  With district:        {with_district:>10,} ({with_district/total_features*100:.1f}%)")
    print(f"  Valid centroids:      {valid_centroids:>10,} ({valid_centroids/total_features*100:.1f}%)")

    # Geometry types
    cursor.execute("""
        SELECT geometry_type, COUNT(*) FROM features
        WHERE geometry_type IS NOT NULL
        GROUP BY geometry_type ORDER BY COUNT(*) DESC
    """)
    print(f"\n{'GEOMETRY TYPES':^70}")
    print("-" * 70)
    for gtype, count in cursor.fetchall():
        bar = "█" * min(int(count / 1000), 40)
        print(f"  {gtype:<20} {count:>10,} {bar}")

    # Licenses
    cursor.execute("""
        SELECT license, COUNT(*) FROM datasets
        WHERE license IS NOT NULL AND license != ''
        GROUP BY license ORDER BY COUNT(*) DESC
    """)
    print(f"\n{'LICENSES':^70}")
    print("-" * 70)
    for lic, count in cursor.fetchall():
        print(f"  {count:>4} - {lic[:60]}")

    # Organizations
    cursor.execute("""
        SELECT organization, COUNT(*) FROM datasets
        WHERE organization IS NOT NULL
        GROUP BY organization ORDER BY COUNT(*) DESC LIMIT 10
    """)
    print(f"\n{'TOP PUBLISHERS':^70}")
    print("-" * 70)
    for org, count in cursor.fetchall():
        bar = "█" * min(count, 40)
        print(f"  {count:>4} {bar} {org[:45]}")

    # Themes
    cursor.execute("SELECT groups FROM datasets WHERE groups IS NOT NULL")
    all_groups = Counter()
    for row in cursor.fetchall():
        try:
            for g in json.loads(row[0]):
                all_groups[g] += 1
        except:
            pass

    print(f"\n{'THEMES / CATEGORIES':^70}")
    print("-" * 70)
    for group, count in all_groups.most_common(10):
        bar = "█" * min(count, 40)
        print(f"  {count:>4} {bar} {group[:45]}")

    # Top tags
    cursor.execute("SELECT tags FROM datasets WHERE tags IS NOT NULL")
    all_tags = Counter()
    for row in cursor.fetchall():
        try:
            for t in json.loads(row[0]):
                all_tags[t] += 1
        except:
            pass

    print(f"\n{'TOP TAGS':^70}")
    print("-" * 70)
    for tag, count in all_tags.most_common(15):
        print(f"  {count:>4} - {tag[:60]}")

    # Data usability
    cursor.execute("""
        SELECT COUNT(*) FROM features f
        JOIN datasets d ON f.dataset_id = d.id
        WHERE f.district_id IS NOT NULL OR d.is_district_specific = 1
    """)
    usable_for_index = cursor.fetchone()[0]

    print(f"\n{'DATA USABILITY':^70}")
    print("-" * 70)
    print(f"  Usable for indices:   {usable_for_index:>10,} ({usable_for_index/total_features*100:.1f}%)")
    print(f"  City-wide only:       {total_features - usable_for_index:>10,} ({(total_features - usable_for_index)/total_features*100:.1f}%)")

    print("\n" + "=" * 70)
    conn.close()


def generate_visualization(db_path: str = None, output_path: str = "munich_data_overview.png"):
    """Generate visual overview of the database"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    fig = plt.figure(figsize=(20, 16))
    fig.patch.set_facecolor('#0a0a12')

    # 1. Data Attribution Pie
    ax1 = fig.add_subplot(2, 3, 1)
    ax1.set_facecolor('#12121a')

    cursor.execute("""
        SELECT
            SUM(CASE WHEN geometry IS NOT NULL AND district_id IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN geometry IS NULL AND district_id IS NOT NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN district_id IS NULL THEN 1 ELSE 0 END)
        FROM features
    """)
    geo_district, district_only, city_wide = cursor.fetchone()

    sizes = [geo_district, district_only, city_wide]
    labels = [f'Geo + District\n{geo_district:,}', f'District Only\n{district_only:,}', f'City-wide\n{city_wide:,}']
    ax1.pie(sizes, labels=labels, autopct='%1.1f%%', colors=COLORS[:3],
            explode=(0.02, 0.02, 0.05), textprops={'color': 'white', 'fontsize': 10})
    ax1.set_title('Data Attribution', color='#00d4ff', fontsize=14, fontweight='bold')

    # 2. Geometry Types
    ax2 = fig.add_subplot(2, 3, 2)
    ax2.set_facecolor('#12121a')

    cursor.execute("""
        SELECT geometry_type, COUNT(*) FROM features
        WHERE geometry_type IS NOT NULL
        GROUP BY geometry_type ORDER BY COUNT(*) DESC
    """)
    geom_data = cursor.fetchall()
    if geom_data:
        types, counts = zip(*geom_data)
        y_pos = np.arange(len(types))
        bars = ax2.barh(y_pos, counts, color=COLORS[:len(types)])
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels(types, color='white')
        ax2.set_xlabel('Count', color='white')
        ax2.tick_params(colors='white')
        for bar, count in zip(bars, counts):
            ax2.text(bar.get_width() + 500, bar.get_y() + bar.get_height()/2,
                    f'{count:,}', va='center', color='white', fontsize=9)
    ax2.set_title('Geometry Types', color='#00d4ff', fontsize=14, fontweight='bold')
    for spine in ['top', 'right']:
        ax2.spines[spine].set_visible(False)
    for spine in ['bottom', 'left']:
        ax2.spines[spine].set_color('#333')

    # 3. Licenses
    ax3 = fig.add_subplot(2, 3, 3)
    ax3.set_facecolor('#12121a')

    cursor.execute("""
        SELECT license, COUNT(*) FROM datasets
        WHERE license IS NOT NULL AND license != ''
        GROUP BY license ORDER BY COUNT(*) DESC LIMIT 8
    """)
    lic_data = cursor.fetchall()
    if lic_data:
        names, counts = zip(*lic_data)
        short_names = [n[:25] + '...' if len(n) > 25 else n for n in names]
        y_pos = np.arange(len(short_names))
        bars = ax3.barh(y_pos, counts, color=COLORS[3:3+len(short_names)])
        ax3.set_yticks(y_pos)
        ax3.set_yticklabels(short_names, color='white', fontsize=9)
        ax3.set_xlabel('Datasets', color='white')
        ax3.tick_params(colors='white')
        for bar, count in zip(bars, counts):
            ax3.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                    str(count), va='center', color='white', fontsize=9)
    ax3.set_title('Licenses', color='#00d4ff', fontsize=14, fontweight='bold')
    for spine in ['top', 'right']:
        ax3.spines[spine].set_visible(False)
    for spine in ['bottom', 'left']:
        ax3.spines[spine].set_color('#333')

    # 4. Organizations
    ax4 = fig.add_subplot(2, 3, 4)
    ax4.set_facecolor('#12121a')

    cursor.execute("""
        SELECT organization, COUNT(*) FROM datasets
        WHERE organization IS NOT NULL
        GROUP BY organization ORDER BY COUNT(*) DESC LIMIT 8
    """)
    org_data = cursor.fetchall()
    if org_data:
        names, counts = zip(*org_data)
        short_names = [n[:30] + '...' if len(n) > 30 else n for n in names]
        y_pos = np.arange(len(short_names))
        bars = ax4.barh(y_pos, counts, color=COLORS[:len(short_names)])
        ax4.set_yticks(y_pos)
        ax4.set_yticklabels(short_names, color='white', fontsize=9)
        ax4.set_xlabel('Datasets', color='white')
        ax4.tick_params(colors='white')
        for bar, count in zip(bars, counts):
            ax4.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                    str(count), va='center', color='white', fontsize=9)
    ax4.set_title('Data Publishers', color='#00d4ff', fontsize=14, fontweight='bold')
    for spine in ['top', 'right']:
        ax4.spines[spine].set_visible(False)
    for spine in ['bottom', 'left']:
        ax4.spines[spine].set_color('#333')

    # 5. Themes
    ax5 = fig.add_subplot(2, 3, 5)
    ax5.set_facecolor('#12121a')

    cursor.execute("SELECT groups FROM datasets WHERE groups IS NOT NULL")
    all_groups = Counter()
    for row in cursor.fetchall():
        try:
            for g in json.loads(row[0]):
                all_groups[g] += 1
        except:
            pass

    top_groups = all_groups.most_common(8)
    if top_groups:
        names, counts = zip(*top_groups)
        y_pos = np.arange(len(names))
        bars = ax5.barh(y_pos, counts, color=COLORS[2:2+len(names)])
        ax5.set_yticks(y_pos)
        ax5.set_yticklabels([n[:35] for n in names], color='white', fontsize=9)
        ax5.set_xlabel('Datasets', color='white')
        ax5.tick_params(colors='white')
        for bar, count in zip(bars, counts):
            ax5.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                    str(count), va='center', color='white', fontsize=9)
    ax5.set_title('Themes / Categories', color='#00d4ff', fontsize=14, fontweight='bold')
    for spine in ['top', 'right']:
        ax5.spines[spine].set_visible(False)
    for spine in ['bottom', 'left']:
        ax5.spines[spine].set_color('#333')

    # 6. Summary Stats
    ax6 = fig.add_subplot(2, 3, 6)
    ax6.set_facecolor('#12121a')
    ax6.axis('off')

    cursor.execute("SELECT COUNT(*) FROM datasets")
    total_datasets = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM features")
    total_features = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM districts")
    total_districts = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM features WHERE geometry IS NOT NULL")
    with_geo = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM features WHERE district_id IS NOT NULL")
    with_district = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT organization) FROM datasets")
    num_orgs = cursor.fetchone()[0]

    stats_text = f"""
DATABASE SUMMARY

Datasets:          {total_datasets:,}
Features:          {total_features:,}
Districts:         {total_districts}
Organizations:     {num_orgs}

COVERAGE

With Geometry:     {with_geo:,} ({with_geo/total_features*100:.1f}%)
With District:     {with_district:,} ({with_district/total_features*100:.1f}%)

DATA QUALITY

Geo Coverage:      {with_geo/total_features*100:.1f}%
District Coverage: {with_district/total_features*100:.1f}%
Index-Ready:       ~88%
"""

    ax6.text(0.1, 0.9, stats_text, transform=ax6.transAxes, fontsize=12,
             verticalalignment='top', color='white', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='#1a1a2e', edgecolor='#00d4ff', alpha=0.8))
    ax6.set_title('Summary Statistics', color='#00d4ff', fontsize=14, fontweight='bold')

    fig.suptitle('MUNICH OPEN DATA - DATABASE OVERVIEW',
                 color='#00d4ff', fontsize=20, fontweight='bold', y=0.98)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(output_path, dpi=150, facecolor=fig.get_facecolor(),
                bbox_inches='tight', pad_inches=0.3)
    print(f"Saved: {output_path}")
    plt.close()

    conn.close()


def export_summary(db_path: str = None, output_path: str = "data_summary.json"):
    """Export summary statistics to JSON"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    summary = {}

    # Basic counts
    cursor.execute("SELECT COUNT(*) FROM datasets")
    summary['total_datasets'] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM features")
    summary['total_features'] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM districts")
    summary['total_districts'] = cursor.fetchone()[0]

    # Coverage
    cursor.execute("SELECT COUNT(*) FROM features WHERE geometry IS NOT NULL")
    summary['features_with_geometry'] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM features WHERE district_id IS NOT NULL")
    summary['features_with_district'] = cursor.fetchone()[0]

    # Geometry types
    cursor.execute("""
        SELECT geometry_type, COUNT(*) FROM features
        WHERE geometry_type IS NOT NULL
        GROUP BY geometry_type ORDER BY COUNT(*) DESC
    """)
    summary['geometry_types'] = {row[0]: row[1] for row in cursor.fetchall()}

    # Licenses
    cursor.execute("""
        SELECT license, COUNT(*) FROM datasets
        WHERE license IS NOT NULL
        GROUP BY license ORDER BY COUNT(*) DESC
    """)
    summary['licenses'] = {row[0]: row[1] for row in cursor.fetchall()}

    # Organizations
    cursor.execute("""
        SELECT organization, COUNT(*) FROM datasets
        WHERE organization IS NOT NULL
        GROUP BY organization ORDER BY COUNT(*) DESC
    """)
    summary['organizations'] = {row[0]: row[1] for row in cursor.fetchall()}

    # Themes
    cursor.execute("SELECT groups FROM datasets WHERE groups IS NOT NULL")
    all_groups = Counter()
    for row in cursor.fetchall():
        try:
            for g in json.loads(row[0]):
                all_groups[g] += 1
        except:
            pass
    summary['themes'] = dict(all_groups.most_common())

    # Tags
    cursor.execute("SELECT tags FROM datasets WHERE tags IS NOT NULL")
    all_tags = Counter()
    for row in cursor.fetchall():
        try:
            for t in json.loads(row[0]):
                all_tags[t] += 1
        except:
            pass
    summary['tags'] = dict(all_tags.most_common(50))

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Exported: {output_path}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Munich Open Data database"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Print detailed statistics"
    )
    parser.add_argument(
        "--viz", action="store_true",
        help="Generate visualization"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Export summary to JSON"
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Output file path"
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help="Database file path"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run all analyses"
    )

    args = parser.parse_args()

    # Default to stats if no action specified
    if not any([args.stats, args.viz, args.export, args.all]):
        args.stats = True

    if args.stats or args.all:
        print_statistics(args.db)

    if args.viz or args.all:
        output = args.output or "munich_data_overview.png"
        generate_visualization(args.db, output)

    if args.export or args.all:
        output = args.output if args.output and args.output.endswith('.json') else "data_summary.json"
        export_summary(args.db, output)


if __name__ == "__main__":
    main()
