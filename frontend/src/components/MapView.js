import React, { useMemo, useEffect, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polygon, LayersControl, FeatureGroup, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import proj4 from 'proj4';
import 'leaflet/dist/leaflet.css';
import './MapView.css';

const { Overlay } = LayersControl;

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

function MapView({ results, datasetMetadata = {}, onMapMove }) {
  // Munich center coordinates
  const munichCenter = [48.1351, 11.5820];

  // Group and process results by category (dataset)
  const groupedData = useMemo(() => {
    const groups = {};

    results.forEach((f) => {
      if (!f.geometry) return;

      const category = f.category || 'unknown';
      if (!groups[category]) {
        groups[category] = { points: [], polygons: [] };
      }

      if (f.geometry.type === 'Point') {
        const position = convertCoordinates(f.geometry.coordinates);
        if (position) {
          groups[category].points.push({ ...f, position });
        }
      } else if (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') {
        try {
          let positions;
          if (f.geometry.type === 'Polygon') {
            positions = f.geometry.coordinates[0].map(coord => convertCoordinates(coord)).filter(Boolean);
          } else {
            // MultiPolygon - take first polygon
            positions = f.geometry.coordinates[0][0].map(coord => convertCoordinates(coord)).filter(Boolean);
          }
          if (positions.length > 0) {
            groups[category].polygons.push({ ...f, positions });
          }
        } catch (error) {
          console.error('Polygon conversion error:', error);
        }
      }
    });

    return groups;
  }, [results]);

  // Get category color
  const getCategoryColor = useCallback((category) => {
    // Use dynamic color generation for dataset IDs
    return stringToColor(category || 'default');
  }, []);

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

  // Check if we have any data to display
  const hasData = Object.keys(groupedData).length > 0;
  const totalPoints = Object.values(groupedData).reduce((sum, g) => sum + g.points.length, 0);
  const totalPolygons = Object.values(groupedData).reduce((sum, g) => sum + g.polygons.length, 0);

  // Apply colors to layer control labels
  useEffect(() => {
    let attempts = 0;
    const maxAttempts = 10;

    const applyColors = () => {
      const labels = document.querySelectorAll('.leaflet-control-layers-overlays label');

      if (labels.length === 0 && attempts < maxAttempts) {
        attempts++;
        setTimeout(applyColors, 100);
        return;
      }

      Object.keys(groupedData).forEach((category, index) => {
        if (labels[index]) {
          const color = getCategoryColor(category);
          labels[index].style.setProperty('--layer-color', color);
        }
      });
    };

    const timer = setTimeout(applyColors, 100);
    return () => clearTimeout(timer);
  }, [groupedData, getCategoryColor]);

  if (!hasData) {
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

        <LayersControl position="topright" collapsed={false}>
          {/* Render each dataset as a separate layer */}
          {Object.entries(groupedData).map(([category, data], index) => {
            const color = getCategoryColor(category);
            const metadata = datasetMetadata[category];
            const datasetName = metadata?.title || category.substring(0, 12) + '...';
            const layerName = `${datasetName} (${data.points.length + data.polygons.length})`;

            return (
              <Overlay key={category} checked name={layerName}>
                <FeatureGroup>
                  {/* Render polygons for this dataset */}
                  {data.polygons.map((feature, index) => (
                    <Polygon
                      key={`polygon-${category}-${index}`}
                      positions={feature.positions}
                      pathOptions={{
                        color: color,
                        fillColor: color,
                        fillOpacity: 0.3,
                        weight: 2
                      }}
                    >
                      <Popup maxWidth={320}>
                        <div className="popup-content">
                          <div className="popup-category" style={{ color: color, fontWeight: 'bold', marginBottom: '8px' }}>
                            Dataset: {category.substring(0, 12)}...
                          </div>
                          {feature.properties && (
                            <div className="popup-properties">
                              {Object.entries(feature.properties)
                                .filter(([key, value]) => value && !key.includes('coord') && !key.includes('shape') && !key.includes('objectid'))
                                .slice(0, 8)
                                .map(([key, value]) => (
                                  <div key={key} style={{ marginBottom: '4px' }}>
                                    <strong style={{ textTransform: 'capitalize' }}>{key.replace('_', ' ')}:</strong> {String(value)}
                                  </div>
                                ))}
                            </div>
                          )}
                        </div>
                      </Popup>
                    </Polygon>
                  ))}

                  {/* Render points for this dataset */}
                  {data.points.map((feature, index) => (
                    <Marker
                      key={`marker-${category}-${index}`}
                      position={feature.position}
                      icon={createIcon(category)}
                    >
                      <Popup maxWidth={320}>
                        <div className="popup-content">
                          <div className="popup-category" style={{ color: color, fontWeight: 'bold', marginBottom: '8px' }}>
                            Dataset: {category.substring(0, 12)}...
                          </div>
                          {feature.properties && (
                            <div className="popup-properties">
                              {Object.entries(feature.properties)
                                .filter(([key, value]) => value && !key.includes('coord') && !key.includes('shape') && typeof value === 'string' && value.length < 200)
                                .slice(0, 6)
                                .map(([key, value]) => (
                                  <div key={key} style={{ marginBottom: '4px' }}>
                                    <strong style={{ textTransform: 'capitalize' }}>{key.replace('_', ' ')}:</strong> {value}
                                  </div>
                                ))}
                            </div>
                          )}
                          <div className="popup-nav-buttons" style={{ marginTop: '12px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                            <a href={`https://maps.apple.com/?q=${feature.position[0]},${feature.position[1]}`} target="_blank" rel="noopener noreferrer"
                              style={{ padding: '6px 10px', background: '#000', color: 'white', textDecoration: 'none', borderRadius: '6px', fontSize: '0.85rem', fontWeight: '500' }}>
                              🍎 Apple Maps
                            </a>
                            <a href={`https://www.google.com/maps/search/?api=1&query=${feature.position[0]},${feature.position[1]}`} target="_blank" rel="noopener noreferrer"
                              style={{ padding: '6px 10px', background: '#4285f4', color: 'white', textDecoration: 'none', borderRadius: '6px', fontSize: '0.85rem', fontWeight: '500' }}>
                              🗺️ Google Maps
                            </a>
                          </div>
                        </div>
                      </Popup>
                    </Marker>
                  ))}
                </FeatureGroup>
              </Overlay>
            );
          })}
        </LayersControl>
      </MapContainer>

      <div className="map-info">
        Displaying {totalPolygons} area{totalPolygons !== 1 ? 's' : ''}
        {totalPolygons > 0 && totalPoints > 0 && ' and '}
        {totalPoints > 0 && `${totalPoints} location${totalPoints !== 1 ? 's' : ''}`} across {Object.keys(groupedData).length} dataset{Object.keys(groupedData).length !== 1 ? 's' : ''}
      </div>
    </div>
  );
}

export default MapView;
