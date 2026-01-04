import React, { useMemo, useEffect, useCallback, useState } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polygon, Polyline, LayersControl, FeatureGroup, useMapEvents, GeoJSON } from 'react-leaflet';
import L from 'leaflet';
import proj4 from 'proj4';
import 'leaflet/dist/leaflet.css';
import './MapView.css';

const { Overlay, BaseLayer } = LayersControl;

// API base URL
const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:5001';

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

// District colors for choropleth - red to green gradient
const DISTRICT_COLORS = [
  '#fee2e2', '#fecaca', '#fca5a5', // Low (red tones)
  '#fef3c7', '#fde68a', '#fcd34d', // Medium-low (yellow tones)
  '#d1fae5', '#a7f3d0', '#6ee7b7', // Medium-high (light green)
  '#34d399'                         // High (green)
];

const getDistrictColor = (value, min, max) => {
  if (value === undefined || value === null) return '#e0e0e0';
  const normalized = Math.min(1, Math.max(0, (value - min) / (max - min)));
  const index = Math.floor(normalized * (DISTRICT_COLORS.length - 1));
  return DISTRICT_COLORS[index];
};

function MapView({ results, datasetMetadata = {}, onMapMove, showDistricts = true, districtData = null, onDistrictClick = null }) {
  // State for district boundaries
  const [districts, setDistricts] = useState(null);
  const [districtsLoading, setDistrictsLoading] = useState(false);
  const [selectedDistrict, setSelectedDistrict] = useState(null);
  const [hoveredDistrict, setHoveredDistrict] = useState(null);

  // Fetch district boundaries
  useEffect(() => {
    if (!showDistricts) return;

    const fetchDistricts = async () => {
      setDistrictsLoading(true);
      try {
        const response = await fetch(`${API_BASE}/api/districts`);
        if (response.ok) {
          const data = await response.json();
          if (data.success && data.data) {
            setDistricts(data.data);
          }
        }
      } catch (error) {
        console.error('Failed to fetch districts:', error);
      } finally {
        setDistrictsLoading(false);
      }
    };

    fetchDistricts();
  }, [showDistricts]);

  // Style for district polygons
  const getDistrictStyle = useCallback((feature) => {
    const isSelected = selectedDistrict === feature.properties?.district_id;
    const isHovered = hoveredDistrict === feature.properties?.district_id;

    // Check if we have choropleth data
    let fillColor = '#3388ff';
    let fillOpacity = 0.1;

    if (districtData && feature.properties?.district_number) {
      // Handle new data structure: {data: {...}, min, max, label}
      const dataMap = districtData.data || districtData;
      const districtValue = dataMap[feature.properties.district_number];
      const value = typeof districtValue === 'object' ? districtValue?.value : districtValue;

      if (value !== undefined && value !== null) {
        // Use pre-computed min/max if available, otherwise calculate
        const min = districtData.min ?? Math.min(...Object.values(dataMap).map(v => typeof v === 'object' ? v.value : v).filter(v => v !== undefined));
        const max = districtData.max ?? Math.max(...Object.values(dataMap).map(v => typeof v === 'object' ? v.value : v).filter(v => v !== undefined));
        fillColor = getDistrictColor(value, min, max);
        fillOpacity = 0.7;
      }
    }

    return {
      color: isSelected ? '#ff4444' : isHovered ? '#1a1a2e' : '#1a1a2e',
      weight: isSelected ? 3 : isHovered ? 2 : 1,
      fillColor: fillColor,
      fillOpacity: isHovered ? Math.min(fillOpacity + 0.15, 0.9) : fillOpacity,
      dashArray: isSelected ? null : null
    };
  }, [selectedDistrict, hoveredDistrict, districtData]);

  // District event handlers
  const onEachDistrict = useCallback((feature, layer) => {
    const props = feature.properties || {};

    layer.on({
      mouseover: (e) => {
        setHoveredDistrict(props.district_id);
        e.target.setStyle({
          weight: 2,
          fillOpacity: 0.4
        });
      },
      mouseout: (e) => {
        setHoveredDistrict(null);
        e.target.setStyle(getDistrictStyle(feature));
      },
      click: (e) => {
        setSelectedDistrict(props.district_id === selectedDistrict ? null : props.district_id);
        if (onDistrictClick) {
          onDistrictClick(props);
        }
      }
    });

    // Bind popup
    let scoreValue = null;
    let scoreLabel = 'Score';

    if (districtData && props.district_number) {
      const dataMap = districtData.data || districtData;
      const districtValue = dataMap[props.district_number];
      scoreValue = typeof districtValue === 'object' ? districtValue?.value : districtValue;
      scoreLabel = districtData.label || 'Score';
    }

    const formattedScore = scoreValue !== null && scoreValue !== undefined
      ? scoreValue.toFixed(1)
      : null;

    const popupContent = `
      <div class="district-popup">
        <h4 style="margin: 0 0 8px 0; color: #1a1a2e; font-size: 1rem;">${props.district_name || 'District'}</h4>
        <div style="font-size: 0.875rem; color: #444;">
          ${formattedScore !== null ? `
            <div style="background: #f8f9fa; padding: 8px 12px; border-radius: 6px; margin-bottom: 8px;">
              <div style="font-size: 0.75rem; color: #666; margin-bottom: 2px;">${scoreLabel}</div>
              <div style="font-size: 1.5rem; font-weight: 700; color: #0066cc;">${formattedScore}</div>
            </div>
          ` : ''}
          <div style="color: #888; font-size: 0.8rem;">District ${props.district_number || 'N/A'}</div>
          ${props.area_sqm ? `<div style="color: #888; font-size: 0.8rem;">${(props.area_sqm / 1000000).toFixed(2)} km²</div>` : ''}
        </div>
      </div>
    `;
    layer.bindPopup(popupContent);
  }, [selectedDistrict, districtData, onDistrictClick, getDistrictStyle]);

  // Munich center coordinates
  const munichCenter = [48.1351, 11.5820];

  // Group and process results by category (dataset)
  const groupedData = useMemo(() => {
    const groups = {};

    results.forEach((f) => {
      if (!f.geometry) return;

      const category = f.category || 'unknown';
      if (!groups[category]) {
        groups[category] = { points: [], polygons: [], lines: [] };
      }

      if (f.geometry.type === 'Point') {
        const position = convertCoordinates(f.geometry.coordinates);
        if (position) {
          groups[category].points.push({ ...f, position });
        }
      } else if (f.geometry.type === 'LineString') {
        try {
          const positions = f.geometry.coordinates.map(coord => convertCoordinates(coord)).filter(Boolean);
          if (positions.length > 1) {
            groups[category].lines.push({ ...f, positions });
          }
        } catch (error) {
          console.error('LineString conversion error:', error);
        }
      } else if (f.geometry.type === 'MultiLineString') {
        try {
          // Handle each line in the MultiLineString
          f.geometry.coordinates.forEach((line, idx) => {
            const positions = line.map(coord => convertCoordinates(coord)).filter(Boolean);
            if (positions.length > 1) {
              groups[category].lines.push({ ...f, positions, lineIndex: idx });
            }
          });
        } catch (error) {
          console.error('MultiLineString conversion error:', error);
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
  const totalLines = Object.values(groupedData).reduce((sum, g) => sum + g.lines.length, 0);
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

  // Show map if we have data OR if we're showing districts
  if (!hasData && !showDistricts) {
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

        {/* District boundaries layer */}
        {showDistricts && districts && districts.features && (
          <GeoJSON
            key={`districts-${selectedDistrict}-${JSON.stringify(districtData || {})}`}
            data={districts}
            style={getDistrictStyle}
            onEachFeature={onEachDistrict}
          />
        )}

        <LayersControl position="topright" collapsed={false}>
          {/* Render each dataset as a separate layer */}
          {Object.entries(groupedData).map(([category, data], index) => {
            const color = getCategoryColor(category);
            const metadata = datasetMetadata[category];
            const datasetName = metadata?.title || category.substring(0, 12) + '...';
            const featureCount = data.points.length + data.lines.length + data.polygons.length;
            const layerName = `${datasetName} (${featureCount})`;

            return (
              <Overlay key={category} checked name={layerName}>
                <FeatureGroup>
                  {/* Render lines for this dataset */}
                  {data.lines.map((feature, index) => (
                    <Polyline
                      key={`line-${category}-${index}`}
                      positions={feature.positions}
                      pathOptions={{
                        color: color,
                        weight: 3,
                        opacity: 0.8
                      }}
                    >
                      <Popup maxWidth={320}>
                        <div className="popup-content">
                          <div className="popup-category" style={{ color: color, fontWeight: 'bold', marginBottom: '8px' }}>
                            {metadata?.title || category}
                          </div>
                          {feature.properties && (
                            <div className="popup-properties">
                              {Object.entries(feature.properties)
                                .filter(([key, value]) => value && !key.startsWith('_') && !key.includes('coord') && !key.includes('shape') && !key.includes('objectid') && !key.includes('dataset_id') && !key.includes('feature_id') && !key.includes('district_id'))
                                .slice(0, 8)
                                .map(([key, value]) => (
                                  <div key={key} style={{ marginBottom: '4px' }}>
                                    <strong style={{ textTransform: 'capitalize' }}>{key.replace(/_/g, ' ')}:</strong> {String(value)}
                                  </div>
                                ))}
                            </div>
                          )}
                        </div>
                      </Popup>
                    </Polyline>
                  ))}

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
                            {metadata?.title || category}
                          </div>
                          {feature.properties && (
                            <div className="popup-properties">
                              {Object.entries(feature.properties)
                                .filter(([key, value]) => value && !key.startsWith('_') && !key.includes('coord') && !key.includes('shape') && !key.includes('objectid') && !key.includes('dataset_id') && !key.includes('feature_id') && !key.includes('district_id'))
                                .slice(0, 8)
                                .map(([key, value]) => (
                                  <div key={key} style={{ marginBottom: '4px' }}>
                                    <strong style={{ textTransform: 'capitalize' }}>{key.replace(/_/g, ' ')}:</strong> {String(value)}
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
                            {metadata?.title || category}
                          </div>
                          {feature.properties && (
                            <div className="popup-properties">
                              {Object.entries(feature.properties)
                                .filter(([key, value]) => value && !key.startsWith('_') && !key.includes('coord') && !key.includes('shape') && !key.includes('dataset_id') && !key.includes('feature_id') && !key.includes('district_id') && typeof value === 'string' && value.length < 200)
                                .slice(0, 6)
                                .map(([key, value]) => (
                                  <div key={key} style={{ marginBottom: '4px' }}>
                                    <strong style={{ textTransform: 'capitalize' }}>{key.replace(/_/g, ' ')}:</strong> {value}
                                  </div>
                                ))}
                            </div>
                          )}
                          <div className="popup-nav-buttons" style={{ marginTop: '12px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                            <a href={`https://maps.apple.com/?q=${feature.position[0]},${feature.position[1]}`} target="_blank" rel="noopener noreferrer"
                              style={{ padding: '6px 10px', background: '#000', color: 'white', textDecoration: 'none', borderRadius: '6px', fontSize: '0.85rem', fontWeight: '500' }}>
                              Apple Maps
                            </a>
                            <a href={`https://www.google.com/maps/search/?api=1&query=${feature.position[0]},${feature.position[1]}`} target="_blank" rel="noopener noreferrer"
                              style={{ padding: '6px 10px', background: '#4285f4', color: 'white', textDecoration: 'none', borderRadius: '6px', fontSize: '0.85rem', fontWeight: '500' }}>
                              Google Maps
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
        {districts && (
          <span className="district-info">
            {districts.features?.length || 0} districts
            {selectedDistrict && ' (1 selected)'}
            {(totalPoints > 0 || totalLines > 0 || totalPolygons > 0) && ' | '}
          </span>
        )}
        {(totalPoints > 0 || totalLines > 0 || totalPolygons > 0) && (
          <>
            {totalPoints > 0 && `${totalPoints} point${totalPoints !== 1 ? 's' : ''}`}
            {totalPoints > 0 && (totalLines > 0 || totalPolygons > 0) && ', '}
            {totalLines > 0 && `${totalLines} line${totalLines !== 1 ? 's' : ''}`}
            {totalLines > 0 && totalPolygons > 0 && ', '}
            {totalPolygons > 0 && `${totalPolygons} area${totalPolygons !== 1 ? 's' : ''}`}
            {' from '}
            {Object.keys(groupedData).length} dataset{Object.keys(groupedData).length !== 1 ? 's' : ''}
          </>
        )}
      </div>

      {/* District legend for choropleth */}
      {districtData && Object.keys(districtData).length > 0 && (
        <div className="choropleth-legend">
          <div className="legend-title">District Values</div>
          <div className="legend-gradient">
            {DISTRICT_COLORS.map((color, i) => (
              <div key={i} className="legend-color" style={{ backgroundColor: color }} />
            ))}
          </div>
          <div className="legend-labels">
            <span>Low</span>
            <span>High</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default MapView;
