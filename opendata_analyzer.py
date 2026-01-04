#!/usr/bin/env python3
"""
OpenData München Analyzer
Analysiert alle Datensätze im OpenData Portal München
"""

import requests
from collections import Counter
import argparse
import sys

BASE_URL = "https://opendata.muenchen.de/api/3/action"

# Geo-Formate
GEO_FORMATS = {
    'geojson', 'wfs', 'wms', 'kml', 'kmz', 'gpx', 'shp', 'shapefile',
    'gml', 'georss', 'wkt', 'arcgis', 'esri', 'ogc', 'geopackage', 'gpkg'
}


def fetch_all_packages():
    """Holt alle Datensatz-IDs"""
    print("Lade Datensatz-Liste...")
    resp = requests.get(f"{BASE_URL}/package_list")
    resp.raise_for_status()
    return resp.json()["result"]


def fetch_package_details(package_id):
    """Holt Details zu einem Datensatz"""
    resp = requests.get(f"{BASE_URL}/package_show", params={"id": package_id})
    if resp.status_code == 200:
        return resp.json().get("result")
    return None


def is_geo_resource(resource):
    """Prüft ob eine Ressource Geodaten enthält"""
    fmt = (resource.get("format") or "").lower()
    name = (resource.get("name") or "").lower()
    url = (resource.get("url") or "").lower()

    for geo_fmt in GEO_FORMATS:
        if geo_fmt in fmt or geo_fmt in name or geo_fmt in url:
            return True
    return False


def analyze_packages(packages, verbose=False):
    """Analysiert alle Datensätze"""
    stats = {
        "total": 0,
        "geo_datasets": 0,
        "groups": Counter(),
        "formats": Counter(),
        "tags": Counter(),
        "organizations": Counter(),
        "licenses": Counter(),
        "update_frequency": Counter(),
    }

    geo_datasets = []

    total = len(packages)
    for i, pkg_id in enumerate(packages):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"Analysiere Datensatz {i+1}/{total}...")

        pkg = fetch_package_details(pkg_id)
        if not pkg:
            continue

        stats["total"] += 1

        # Groups (Themen)
        for group in pkg.get("groups", []):
            stats["groups"][group.get("title", "Unbekannt")] += 1

        # Tags
        for tag in pkg.get("tags", []):
            stats["tags"][tag.get("name", "")] += 1

        # Organisation
        org = pkg.get("organization", {})
        if org:
            stats["organizations"][org.get("title", "Unbekannt")] += 1

        # Lizenz
        stats["licenses"][pkg.get("license_id", "Unbekannt")] += 1

        # Update-Frequenz
        freq = pkg.get("frequency", "Unbekannt")
        stats["update_frequency"][freq or "Unbekannt"] += 1

        # Ressourcen und Formate
        has_geo = False
        for resource in pkg.get("resources", []):
            fmt = (resource.get("format") or "Unbekannt").upper()
            stats["formats"][fmt] += 1

            if is_geo_resource(resource):
                has_geo = True

        if has_geo:
            stats["geo_datasets"] += 1
            geo_datasets.append(pkg.get("title", pkg_id))

    return stats, geo_datasets


def print_stats(stats, geo_datasets, top_n=15):
    """Gibt die Statistiken aus"""
    print("\n" + "=" * 60)
    print("OPENDATA MÜNCHEN - ANALYSE")
    print("=" * 60)

    # Übersicht
    print(f"\n{'ÜBERSICHT':^60}")
    print("-" * 60)
    print(f"Gesamtzahl Datensätze:     {stats['total']:>6}")
    print(f"Davon mit Geodaten:        {stats['geo_datasets']:>6} ({stats['geo_datasets']/stats['total']*100:.1f}%)")

    # Themen/Groups
    print(f"\n{'THEMEN (Groups)':^60}")
    print("-" * 60)
    for group, count in stats["groups"].most_common(top_n):
        bar = "#" * min(count, 40)
        print(f"{group[:40]:<40} {count:>4} {bar}")

    # Formate
    print(f"\n{'RESSOURCEN-FORMATE':^60}")
    print("-" * 60)
    for fmt, count in stats["formats"].most_common(top_n):
        bar = "#" * min(count // 5, 30)
        print(f"{fmt[:25]:<25} {count:>5} {bar}")

    # Top Tags
    print(f"\n{'TOP TAGS':^60}")
    print("-" * 60)
    for tag, count in stats["tags"].most_common(top_n):
        bar = "#" * min(count, 30)
        print(f"{tag[:35]:<35} {count:>4} {bar}")

    # Organisationen
    print(f"\n{'ORGANISATIONEN':^60}")
    print("-" * 60)
    for org, count in stats["organizations"].most_common(top_n):
        bar = "#" * min(count // 2, 30)
        print(f"{org[:40]:<40} {count:>4} {bar}")

    # Lizenzen
    print(f"\n{'LIZENZEN':^60}")
    print("-" * 60)
    for lic, count in stats["licenses"].most_common():
        pct = count / stats["total"] * 100
        print(f"{lic[:35]:<35} {count:>4} ({pct:>5.1f}%)")

    # Update-Frequenz
    print(f"\n{'UPDATE-FREQUENZ':^60}")
    print("-" * 60)
    for freq, count in stats["update_frequency"].most_common():
        pct = count / stats["total"] * 100
        print(f"{freq[:35]:<35} {count:>4} ({pct:>5.1f}%)")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Analysiert OpenData München Datensätze"
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        default=0,
        help="Limitiere Anzahl der zu analysierenden Datensätze (0 = alle)"
    )
    parser.add_argument(
        "-t", "--top",
        type=int,
        default=15,
        help="Anzahl der Top-Einträge pro Kategorie (default: 15)"
    )
    parser.add_argument(
        "--geo-list",
        action="store_true",
        help="Liste alle Geodaten-Datensätze auf"
    )

    args = parser.parse_args()

    try:
        packages = fetch_all_packages()
        print(f"Gefunden: {len(packages)} Datensätze")

        if args.limit > 0:
            packages = packages[:args.limit]
            print(f"Limitiert auf: {len(packages)} Datensätze")

        stats, geo_datasets = analyze_packages(packages)
        print_stats(stats, geo_datasets, top_n=args.top)

        if args.geo_list and geo_datasets:
            print(f"\n{'GEODATEN-DATENSÄTZE':^60}")
            print("-" * 60)
            for ds in sorted(geo_datasets):
                print(f"  - {ds}")

    except requests.RequestException as e:
        print(f"Fehler beim API-Aufruf: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(0)


if __name__ == "__main__":
    main()
