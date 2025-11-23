import React from 'react';
import proj4 from 'proj4';
import './ResultsList.css';

// Define projection systems
proj4.defs([
  ['EPSG:25832', '+proj=utm +zone=32 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs +type=crs'],
  ['EPSG:4326', '+proj=longlat +datum=WGS84 +no_defs +type=crs']
]);

function ResultsList({ results }) {
  const getCategoryColor = (category) => {
    const colors = {
      markets: '#4CAF50',
      bike_infrastructure: '#2196F3',
      districts: '#FF9800',
      isar_dangers: '#f44336',
      disabled_parking: '#9C27B0',
      waste_disposal: '#795548',
      accessible_glass_containers: '#8BC34A',
      charging_infrastructure: '#FFC107',
      community_centers: '#E91E63',
      bike_service_stations: '#3F51B5',
      environmental_zone: '#009688',
      recycling_islands: '#CDDC39'
    };
    return colors[category] || '#757575';
  };

  const formatKey = (key) => {
    // Convert snake_case to Title Case
    return key
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const convertUTMToLatLon = (coords) => {
    try {
      // Check if coordinates are in projected system (UTM)
      if (coords[0] > 180 || coords[0] < -180) {
        // Convert from EPSG:25832 (UTM) to EPSG:4326 (lat/lon)
        const [lon, lat] = proj4('EPSG:25832', 'EPSG:4326', coords);
        return [lat, lon];
      } else {
        // Already in lat/lon, just swap if needed
        return coords[1] > coords[0] ? [coords[1], coords[0]] : coords;
      }
    } catch (error) {
      console.error('Coordinate conversion error:', error, coords);
      return [48.1351, 11.5820]; // Munich center as fallback
    }
  };

  const getNavigationLinks = (geometry) => {
    if (!geometry || geometry.type !== 'Point') return null;

    const [lat, lon] = convertUTMToLatLon(geometry.coordinates);

    return (
      <div className="navigation-links">
        <div className="nav-label">Open in:</div>
        <div className="nav-buttons">
          <a
            href={`https://maps.apple.com/?q=${lat},${lon}`}
            target="_blank"
            rel="noopener noreferrer"
            className="nav-button apple-maps"
          >
            🍎 Apple Maps
          </a>
          <a
            href={`https://www.google.com/maps/search/?api=1&query=${lat},${lon}`}
            target="_blank"
            rel="noopener noreferrer"
            className="nav-button google-maps"
          >
            🗺️ Google Maps
          </a>
          <a
            href={`https://www.mvg.de/`}
            target="_blank"
            rel="noopener noreferrer"
            className="nav-button mvg"
            title="Open MVG (Munich public transport)"
          >
            🚇 MVG
          </a>
        </div>
      </div>
    );
  };

  const formatValue = (key, value) => {
    // Skip empty values
    if (value === null || value === undefined || value === '') return null;

    // Handle HTML links
    if (typeof value === 'string' && value.includes('<a href=')) {
      const match = value.match(/href="([^"]+)"/);
      if (match) {
        return (
          <a href={match[1]} target="_blank" rel="noopener noreferrer">
            Visit Link
          </a>
        );
      }
    }

    // Handle long text
    if (typeof value === 'string' && value.length > 200) {
      return (
        <details>
          <summary>Show full text ({value.length} characters)</summary>
          <p style={{ marginTop: '0.5rem' }}>{value}</p>
        </details>
      );
    }

    // Handle coordinates
    if (key.includes('coord') && typeof value === 'number') {
      return value.toFixed(4);
    }

    return String(value);
  };

  const getMainTitle = (feature) => {
    const props = feature.properties || {};

    // Try common title fields
    const titleFields = [
      'bezeichnung', 'name', 'adresse', 'lage',
      'inhalt', 'parkplatz_id', 'hinweis'
    ];

    for (const field of titleFields) {
      if (props[field]) {
        const value = String(props[field]);
        // Truncate if too long
        return value.length > 100 ? value.substring(0, 100) + '...' : value;
      }
    }

    return `${feature.category.replace('_', ' ')} Item`;
  };

  const getPrioritizedProperties = (properties) => {
    // Define priority order for different property keys
    const priorityKeys = [
      'bezeichnung', 'adresse', 'name', 'lage', 'inhalt',
      'kategorie', 'rubrik', 'detail', 'stadtbezirk', 'plz',
      'hinweis', 'betrifft', 'link', 'zeitliche_einschraenkung',
      'anzahl_stellplaetze', 'öffnungszeiten', 'kontakt'
    ];

    const sorted = [];
    const remaining = [];

    // Add priority keys first
    priorityKeys.forEach(key => {
      if (properties[key] !== undefined && properties[key] !== null && properties[key] !== '') {
        sorted.push([key, properties[key]]);
      }
    });

    // Add remaining keys
    Object.entries(properties).forEach(([key, value]) => {
      if (!priorityKeys.includes(key) &&
          value !== null &&
          value !== undefined &&
          value !== '' &&
          !key.includes('_coord') &&
          !key.includes('geometry_name')) {
        remaining.push([key, value]);
      }
    });

    return [...sorted, ...remaining];
  };

  if (results.length === 0) {
    return (
      <div className="no-results">
        <h3>No results found</h3>
        <p>Try adjusting your search or filter criteria</p>
      </div>
    );
  }

  return (
    <div className="results-list">
      <div className="results-header">
        Found {results.length} result{results.length !== 1 ? 's' : ''}
      </div>
      {results.map((feature, index) => {
        const prioritizedProps = getPrioritizedProperties(feature.properties || {});

        return (
          <div key={index} className="result-card">
            <div className="result-header">
              <div
                className="category-badge"
                style={{ backgroundColor: getCategoryColor(feature.category) }}
              >
                {feature.category.replace('_', ' ')}
              </div>
              {feature.distance_km && (
                <div className="distance-badge">
                  📍 {feature.distance_km} km away
                </div>
              )}
            </div>

            <h3 className="result-title">{getMainTitle(feature)}</h3>

            <div className="result-content">
              {feature.properties && (
                <div className="properties">
                  {prioritizedProps.slice(0, 10).map(([key, value]) => {
                    const formattedValue = formatValue(key, value);
                    if (!formattedValue) return null;

                    return (
                      <div key={key} className="property">
                        <span className="property-key">{formatKey(key)}:</span>{' '}
                        <span className="property-value">{formattedValue}</span>
                      </div>
                    );
                  })}

                  {prioritizedProps.length > 10 && (
                    <details className="more-properties">
                      <summary>Show {prioritizedProps.length - 10} more properties</summary>
                      <div className="properties" style={{ marginTop: '0.5rem' }}>
                        {prioritizedProps.slice(10).map(([key, value]) => {
                          const formattedValue = formatValue(key, value);
                          if (!formattedValue) return null;

                          return (
                            <div key={key} className="property">
                              <span className="property-key">{formatKey(key)}:</span>{' '}
                              <span className="property-value">{formattedValue}</span>
                            </div>
                          );
                        })}
                      </div>
                    </details>
                  )}
                </div>
              )}

              {feature.geometry && feature.geometry.type === 'Point' && (
                <>
                  {getNavigationLinks(feature.geometry)}
                  <div className="coordinates">
                    📍 Coordinates: {feature.geometry.coordinates[0].toFixed(2)}, {feature.geometry.coordinates[1].toFixed(2)}
                  </div>
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default ResultsList;
