import React from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polygon, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import proj4 from 'proj4';
import 'leaflet/dist/leaflet.css';
import './MapView.css';

function MapEventHandler({ onMapMove }) {
  useMapEvents({
    moveend: (e) => {
      const center = e.target.getCenter();
      onMapMove([center.lat, center.lng]);
    }
  });
  return null;
}

// Fix for default marker icons in React-Leaflet
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: require('leaflet/dist/images/marker-icon-2x.png'),
  iconUrl: require('leaflet/dist/images/marker-icon.png'),
  shadowUrl: require('leaflet/dist/images/marker-shadow.png'),
});

// Define projection systems
// EPSG:25832 - ETRS89 / UTM zone 32N (used in Munich data)
// EPSG:4326 - WGS84 (standard lat/lon used by Leaflet)
proj4.defs([
  ['EPSG:25832', '+proj=utm +zone=32 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs +type=crs'],
  ['EPSG:4326', '+proj=longlat +datum=WGS84 +no_defs +type=crs']
]);

const convertCoordinates = (coords) => {
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
    return null;
  }
};

function MapView({ results, onMapMove }) {
  // Filter and convert point results
  const pointResults = results
    .filter((f) => f.geometry && f.geometry.type === 'Point')
    .map((f) => {
      const position = convertCoordinates(f.geometry.coordinates);
      return position ? { ...f, position } : null;
    })
    .filter(Boolean);

  // Filter and convert polygon results (districts)
  const polygonResults = results
    .filter((f) => f.geometry && (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon'))
    .map((f) => {
      try {
        let positions;
        if (f.geometry.type === 'Polygon') {
          // Single polygon
          positions = f.geometry.coordinates[0].map(coord => convertCoordinates(coord)).filter(Boolean);
        } else {
          // MultiPolygon - take first polygon
          positions = f.geometry.coordinates[0][0].map(coord => convertCoordinates(coord)).filter(Boolean);
        }
        return positions.length > 0 ? { ...f, positions } : null;
      } catch (error) {
        console.error('Polygon conversion error:', error);
        return null;
      }
    })
    .filter(Boolean);

  // Munich center coordinates
  const munichCenter = [48.1351, 11.5820];

  // Generate color from string hash (for dataset IDs)
  const stringToColor = (str) => {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }

    // Generate bright, distinct colors
    const hue = Math.abs(hash % 360);
    const saturation = 65 + (Math.abs(hash >> 8) % 20); // 65-85%
    const lightness = 45 + (Math.abs(hash >> 16) % 15); // 45-60%

    return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
  };

  // Get category color
  const getCategoryColor = (category) => {
    // Use dynamic color generation for dataset IDs
    return stringToColor(category || 'default');
  };

  // Create custom icon with category color
  const createIcon = (category) => {
    const color = getCategoryColor(category);
    return L.divIcon({
      className: 'custom-marker',
      html: `<div style="background-color: ${color}; width: 16px; height: 16px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 6px rgba(0,0,0,0.4);"></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
  };

  if (pointResults.length === 0 && polygonResults.length === 0) {
    return (
      <div className="no-map-results">
        <h3>No location data to display</h3>
        <p>The current results don't contain valid geographic coordinates</p>
      </div>
    );
  }

  return (
    <div className="map-view-wrapper">
      <MapContainer
        center={munichCenter}
        zoom={12}
        minZoom={10}
        maxZoom={18}
        maxBounds={[
          [47.9, 11.2],  // Southwest corner
          [48.3, 11.9]   // Northeast corner
        ]}
        maxBoundsViscosity={1.0}
        className="map-container"
      >
        {onMapMove && <MapEventHandler onMapMove={onMapMove} />}
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Render polygons (districts) */}
        {polygonResults.map((feature, index) => (
          <Polygon
            key={`polygon-${index}`}
            positions={feature.positions}
            pathOptions={{
              color: getCategoryColor(feature.category),
              fillColor: getCategoryColor(feature.category),
              fillOpacity: 0.2,
              weight: 2
            }}
          >
            <Popup maxWidth={320}>
              <div className="popup-content">
                <div
                  className="popup-category"
                  style={{
                    color: getCategoryColor(feature.category),
                    fontWeight: 'bold',
                    marginBottom: '8px'
                  }}
                >
                  {feature.category.replace('_', ' ').toUpperCase()}
                </div>
                {feature.properties && (
                  <div className="popup-properties">
                    {Object.entries(feature.properties)
                      .filter(([key, value]) =>
                        value &&
                        !key.includes('coord') &&
                        !key.includes('shape') &&
                        !key.includes('objectid') &&
                        typeof value !== 'number'
                      )
                      .slice(0, 8)
                      .map(([key, value]) => (
                        <div key={key} style={{ marginBottom: '4px' }}>
                          <strong style={{ textTransform: 'capitalize' }}>{key.replace('_', ' ')}:</strong>{' '}
                          {String(value)}
                        </div>
                      ))}
                  </div>
                )}
              </div>
            </Popup>
          </Polygon>
        ))}

        {/* Render point markers */}
        {pointResults.slice(0, 1000).map((feature, index) => (
          <Marker
            key={`marker-${index}`}
            position={feature.position}
            icon={createIcon(feature.category)}
          >
            <Popup maxWidth={320}>
              <div className="popup-content">
                <div
                  className="popup-category"
                  style={{
                    color: getCategoryColor(feature.category),
                    fontWeight: 'bold',
                    marginBottom: '8px'
                  }}
                >
                  {feature.category.replace('_', ' ').toUpperCase()}
                </div>
                {feature.properties && (
                  <div className="popup-properties">
                    {Object.entries(feature.properties)
                      .filter(([key, value]) =>
                        value &&
                        !key.includes('coord') &&
                        !key.includes('shape') &&
                        typeof value === 'string' &&
                        !value.includes('<a href=') &&
                        value.length < 200
                      )
                      .slice(0, 6)
                      .map(([key, value]) => (
                        <div key={key} style={{ marginBottom: '4px' }}>
                          <strong style={{ textTransform: 'capitalize' }}>{key.replace('_', ' ')}:</strong>{' '}
                          {value}
                        </div>
                      ))}
                  </div>
                )}
                <div className="popup-nav-buttons" style={{ marginTop: '12px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  <a
                    href={`https://maps.apple.com/?q=${feature.position[0]},${feature.position[1]}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      padding: '6px 10px',
                      background: '#000',
                      color: 'white',
                      textDecoration: 'none',
                      borderRadius: '6px',
                      fontSize: '0.85rem',
                      fontWeight: '500'
                    }}
                  >
                    🍎 Apple Maps
                  </a>
                  <a
                    href={`https://www.google.com/maps/search/?api=1&query=${feature.position[0]},${feature.position[1]}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      padding: '6px 10px',
                      background: '#4285f4',
                      color: 'white',
                      textDecoration: 'none',
                      borderRadius: '6px',
                      fontSize: '0.85rem',
                      fontWeight: '500'
                    }}
                  >
                    🗺️ Google Maps
                  </a>
                  <a
                    href={`https://www.mvg.de/`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      padding: '6px 10px',
                      background: '#0065bd',
                      color: 'white',
                      textDecoration: 'none',
                      borderRadius: '6px',
                      fontSize: '0.85rem',
                      fontWeight: '500'
                    }}
                    title="Munich public transport"
                  >
                    🚇 MVG
                  </a>
                </div>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
      {pointResults.length > 1000 && (
        <div className="map-notice">
          Showing first 1000 of {pointResults.length} results on map
        </div>
      )}
      <div className="map-info">
        Displaying {polygonResults.length} area{polygonResults.length !== 1 ? 's' : ''}
        {polygonResults.length > 0 && pointResults.length > 0 && ' and '}
        {pointResults.length > 0 && `${Math.min(pointResults.length, 1000)} location${pointResults.length !== 1 ? 's' : ''}`} on map
      </div>
    </div>
  );
}

export default MapView;
