import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import MapView from './components/MapView';
import Chatbot from './components/Chatbot';
import Tooltip from './components/Tooltip';
import './App.css';

const API_URL = `http://${window.location.hostname}:5001/api`;

// Translations
const TRANSLATIONS = {
  en: {
    title: 'Munich Data',
    districtIndices: 'District Indices',
    customIndex: '+ Custom Index',
    hideBuilder: '− Hide Builder',
    addDataset: 'Add dataset...',
    calculate: 'Calculate',
    calculating: 'Calculating...',
    colorOverlay: 'Color overlay',
    dataPoints: 'Data points',
    editIndex: 'Edit Index',
    close: 'Close',
    normalization: {
      population: '/capita',
      area: '/km²',
      minmax: '0-100',
      none: 'raw'
    },
    aggregation: {
      count: 'Count',
      sum: 'Sum',
      avg: 'Avg'
    },
    normalize: {
      minmax: '0-100',
      population: 'Per Capita',
      area: 'Per km²',
      none: 'Raw'
    }
  },
  de: {
    title: 'München Daten',
    districtIndices: 'Bezirks-Indizes',
    customIndex: '+ Eigener Index',
    hideBuilder: '− Ausblenden',
    addDataset: 'Datensatz hinzufügen...',
    calculate: 'Berechnen',
    calculating: 'Berechne...',
    colorOverlay: 'Farbüberlagerung',
    dataPoints: 'Datenpunkte',
    editIndex: 'Index bearbeiten',
    close: 'Schließen',
    normalization: {
      population: '/Einw.',
      area: '/km²',
      minmax: '0-100',
      none: 'roh'
    },
    aggregation: {
      count: 'Anzahl',
      sum: 'Summe',
      avg: 'Durchschn.'
    },
    normalize: {
      minmax: '0-100',
      population: 'Pro Kopf',
      area: 'Pro km²',
      none: 'Roh'
    }
  }
};

const NORMALIZATION_OPTIONS = (lang) => [
  { value: 'minmax', label: TRANSLATIONS[lang].normalize.minmax },
  { value: 'population', label: TRANSLATIONS[lang].normalize.population },
  { value: 'area', label: TRANSLATIONS[lang].normalize.area },
  { value: 'none', label: TRANSLATIONS[lang].normalize.none },
];

const AGGREGATION_OPTIONS = (lang) => [
  { value: 'count', label: TRANSLATIONS[lang].aggregation.count },
  { value: 'sum', label: TRANSLATIONS[lang].aggregation.sum },
  { value: 'avg', label: TRANSLATIONS[lang].aggregation.avg },
];

// Counter for generating unique component IDs
let componentIdCounter = 0;

function App() {
  // Language
  const [lang, setLang] = useState(() => {
    const saved = localStorage.getItem('openatlas-lang');
    return saved || (navigator.language.startsWith('de') ? 'de' : 'en');
  });
  const t = TRANSLATIONS[lang];

  const toggleLang = () => {
    const newLang = lang === 'en' ? 'de' : 'en';
    setLang(newLang);
    localStorage.setItem('openatlas-lang', newLang);
  };

  // Index state
  const [presets, setPresets] = useState([]);
  const [selectedPreset, setSelectedPreset] = useState(null);
  const [indexResult, setIndexResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showOverlay, setShowOverlay] = useState(true);
  const [showDataPoints, setShowDataPoints] = useState(true);

  // Custom index
  const [showCustomBuilder, setShowCustomBuilder] = useState(false);
  const [availableDatasets, setAvailableDatasets] = useState([]);
  const [customComponents, setCustomComponents] = useState([]);
  const [datasetSearch, setDatasetSearch] = useState('');

  // District selection
  const [selectedDistrict, setSelectedDistrict] = useState(null);
  const [districtData, setDistrictData] = useState(null);

  // Map data from index components
  const [mapFeatures, setMapFeatures] = useState([]);
  const [datasetMetadata, setDatasetMetadata] = useState({});

  useEffect(() => {
    loadPresets();
    loadAvailableDatasets();
  }, []);

  const loadPresets = async () => {
    try {
      const response = await axios.get(`${API_URL}/indices/presets`);
      if (response.data.success) {
        setPresets(response.data.presets);
      }
    } catch (error) {
      console.error('Error loading presets:', error);
    }
  };

  const loadAvailableDatasets = async () => {
    try {
      const response = await axios.get(`${API_URL}/indices/datasets`);
      if (response.data.success) {
        setAvailableDatasets(response.data.datasets);
      }
    } catch (error) {
      console.error('Error loading datasets:', error);
    }
  };

  const loadDatasetColumns = async (datasetId) => {
    try {
      const response = await axios.get(`${API_URL}/indices/datasets/${datasetId}/columns`);
      if (response.data.success) {
        return response.data.numeric_columns || [];
      }
    } catch (error) {
      console.error('Error loading columns:', error);
    }
    return [];
  };

  const loadComponentFeatures = async (components) => {
    // Load geometric features from all datasets with geometry
    const allFeatures = [];
    const metadata = {};

    for (const comp of components) {
      if (!comp.dataset_id) continue;

      try {
        const response = await axios.get(`${API_URL}/v2/datasets/${comp.dataset_id}/features`, {
          params: { limit: 500 }
        });

        if (response.data.success && response.data.data?.features) {
          const features = response.data.data.features
            .filter(f => f.geometry) // Only features with geometry
            .map(f => ({
              ...f,
              category: comp.dataset_id
            }));

          allFeatures.push(...features);
          metadata[comp.dataset_id] = {
            title: comp.label,
            weight: comp.weight
          };
        }
      } catch (error) {
        // Some datasets may not have geometry, skip silently
      }
    }

    setMapFeatures(allFeatures);
    setDatasetMetadata(metadata);
  };

  const calculateIndex = useCallback(async (presetId) => {
    setLoading(true);
    setSelectedPreset(presetId);
    setSelectedDistrict(null);

    try {
      const response = await axios.get(`${API_URL}/indices/calculate/${presetId}`);
      if (response.data.success) {
        applyIndexResult(response.data);
        // Load geometric features from component datasets
        await loadComponentFeatures(response.data.components);
      }
    } catch (error) {
      console.error('Error calculating index:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  const calculateCustomIndex = async () => {
    if (customComponents.length === 0) return;

    setLoading(true);
    setSelectedPreset(null);
    setSelectedDistrict(null);

    try {
      const response = await axios.post(`${API_URL}/indices/calculate`, {
        name: 'Custom Index',
        components: customComponents.map(c => ({
          dataset_id: c.dataset.id,
          column: c.column || null,
          weight: c.weight,
          aggregation: c.aggregation,
          normalize: c.normalize,
          label: c.label || c.dataset.title.substring(0, 30)
        }))
      });

      if (response.data.success) {
        applyIndexResult(response.data);
        await loadComponentFeatures(response.data.components);
        setShowCustomBuilder(false);
      }
    } catch (error) {
      console.error('Error calculating custom index:', error);
    } finally {
      setLoading(false);
    }
  };

  const applyIndexResult = (data, suggestedIndex) => {
    setIndexResult(data);

    const mapData = {};
    for (const district of data.districts) {
      const score = data.scores[district.number];
      if (score !== undefined) {
        mapData[district.number] = {
          value: score,
          name: district.name,
        };
      }
    }

    setDistrictData({
      data: mapData,
      min: data.stats.min,
      max: data.stats.max,
      label: data.name || suggestedIndex?.name || 'Chat Index',
    });

    // Clear any preset selection since this came from chat
    setSelectedPreset(null);
  };

  // Handle geographic data from chatbot
  const handleChatGeoData = useCallback((geoData) => {
    if (!geoData || !geoData.coordinates || !Array.isArray(geoData.coordinates)) {
      console.log('No valid geo_data received:', geoData);
      return;
    }

    console.log('Processing geo_data:', geoData.coordinates.length, 'coordinates');

    // Convert chat geo data to map features format
    // Coordinates come as {lat, lon} from the backend
    const features = geoData.coordinates
      .filter(coord => {
        // Validate coordinates
        const lat = coord.lat || coord.latitude;
        const lon = coord.lon || coord.longitude;
        const valid = typeof lat === 'number' && typeof lon === 'number' &&
                      !isNaN(lat) && !isNaN(lon) &&
                      lat >= -90 && lat <= 90 &&
                      lon >= -180 && lon <= 180;
        if (!valid) {
          console.log('Invalid coordinate:', coord);
        }
        return valid;
      })
      .map((coord, idx) => ({
        type: 'Feature',
        geometry: {
          type: 'Point',
          // GeoJSON uses [longitude, latitude] order
          coordinates: [coord.lon || coord.longitude, coord.lat || coord.latitude]
        },
        properties: {
          name: coord.name || `Point ${idx + 1}`,
          ...(coord.properties || {})
        },
        category: 'chat-result'
      }));

    console.log('Created', features.length, 'valid features');

    if (features.length > 0) {
      setMapFeatures(features);
      setDatasetMetadata({
        'chat-result': {
          title: geoData.dataset_title || 'Chat Results',
          weight: 1
        }
      });

      // Clear any district-based visualization to show only points
      setDistrictData(null);
      setIndexResult(null);
      setSelectedPreset(null);
    }
  }, []);

  const clearIndex = () => {
    setSelectedPreset(null);
    setIndexResult(null);
    setDistrictData(null);
    setSelectedDistrict(null);
    setMapFeatures([]);
    setDatasetMetadata({});
  };

  const handleDistrictClick = (props) => {
    if (!indexResult || !props.district_number) return;

    const districtNum = props.district_number;
    const breakdown = indexResult.breakdown?.[districtNum];
    const score = indexResult.scores?.[districtNum];

    if (breakdown) {
      setSelectedDistrict({
        number: districtNum,
        name: props.district_name,
        score: score,
        breakdown: breakdown
      });
    }
  };

  const addComponent = async (dataset) => {
    // Generate a unique ID using a counter for better uniqueness
    componentIdCounter += 1;
    const componentId = `component_${dataset.id}_${componentIdCounter}`;
    const columns = await loadDatasetColumns(dataset.id);
    setCustomComponents([...customComponents, {
      id: componentId,  // Unique ID for this component instance
      dataset,
      columns,
      column: null,
      weight: 1.0,
      normalize: 'minmax',
      aggregation: 'count',
      label: dataset.title.substring(0, 40)
    }]);
    setDatasetSearch('');
  };

  const removeComponent = (componentId) => {
    setCustomComponents(customComponents.filter(c => c.id !== componentId));
  };

  const updateComponent = (componentId, field, value) => {
    setCustomComponents(customComponents.map(c =>
      c.id === componentId ? { ...c, [field]: value } : c
    ));
  };

  const editCurrentIndex = async () => {
    if (!indexResult || !indexResult.components) return;

    const newComponents = [];
    for (const comp of indexResult.components) {
      // Find the dataset in availableDatasets
      const dataset = availableDatasets.find(d => d.id === comp.dataset_id);
      if (dataset) {
        const columns = await loadDatasetColumns(dataset.id);
        componentIdCounter += 1;
        const componentId = `component_${dataset.id}_${componentIdCounter}`;
        newComponents.push({
          id: componentId,  // Unique ID for this component instance
          dataset,
          columns,
          column: comp.column || null,
          weight: comp.weight,
          normalize: comp.normalize || 'minmax',
          aggregation: comp.aggregation || 'count',
          label: comp.label || dataset.title.substring(0, 40)
        });
      }
    }

    if (newComponents.length > 0) {
      setCustomComponents(newComponents);
      setShowCustomBuilder(true);
    }
  };

  const filteredDatasets = availableDatasets.filter(d =>
    d.title.toLowerCase().includes(datasetSearch.toLowerCase())
  ).slice(0, 8);

  return (
    <div className="app">
      {/* Side Panel */}
      <div className="side-panel">
        <div className="panel-header">
          <h1>{t.title}</h1>
          <button className="lang-toggle" onClick={toggleLang}>
            {lang === 'en' ? 'DE' : 'EN'}
          </button>
        </div>

        {/* Presets */}
        <div className="section">
          <h3>{t.districtIndices}</h3>
          <div className="preset-list">
            {presets.map((p) => (
              <button
                key={p.id}
                className={`preset-btn ${selectedPreset === p.id ? 'active' : ''}`}
                onClick={() => calculateIndex(p.id)}
                disabled={loading}
              >
                <span className="preset-icon">{p.icon}</span>
                <span className="preset-name">{p.name}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Custom Builder Toggle */}
        <button
          className="custom-toggle"
          onClick={() => setShowCustomBuilder(!showCustomBuilder)}
        >
          {showCustomBuilder ? t.hideBuilder : t.customIndex}
        </button>

        {/* Custom Builder */}
        {showCustomBuilder && (
          <div className="custom-builder">
            <div className="dataset-search">
              <input
                type="text"
                placeholder={t.addDataset}
                value={datasetSearch}
                onChange={(e) => setDatasetSearch(e.target.value)}
              />
              {datasetSearch && filteredDatasets.length > 0 && (
                <div className="dataset-dropdown">
                  {filteredDatasets.map(d => (
                    <div key={d.id} className="dataset-option" onClick={() => addComponent(d)}>
                      <span className="dataset-title">{d.title}</span>
                      {d.description && (
                        <Tooltip text={d.description}>
                          <span className="info-icon">ⓘ</span>
                        </Tooltip>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {customComponents.length > 0 && (
              <>
                <div className="component-list">
                  {customComponents.map(c => (
                    <div key={c.id} className="component-card">
                      <div className="component-header">
                        <input
                          type="text"
                          value={c.label}
                          onChange={(e) => updateComponent(c.id, 'label', e.target.value)}
                          className="component-label"
                        />
                        {c.dataset.description && (
                          <Tooltip text={c.dataset.description}>
                            <span className="info-icon">ⓘ</span>
                          </Tooltip>
                        )}
                        <button onClick={() => removeComponent(c.id)}>×</button>
                      </div>

                      <div className="component-options">
                        <select
                          value={c.aggregation}
                          onChange={(e) => updateComponent(c.id, 'aggregation', e.target.value)}
                        >
                          {AGGREGATION_OPTIONS(lang).map(opt => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>

                        {c.aggregation !== 'count' && c.columns.length > 0 && (
                          <select
                            value={c.column || ''}
                            onChange={(e) => updateComponent(c.id, 'column', e.target.value || null)}
                          >
                            <option value="">{lang === 'de' ? 'Spalte...' : 'Column...'}</option>
                            {c.columns.map(col => (
                              <option key={col} value={col}>{col}</option>
                            ))}
                          </select>
                        )}

                        <select
                          value={c.normalize}
                          onChange={(e) => updateComponent(c.id, 'normalize', e.target.value)}
                        >
                          {NORMALIZATION_OPTIONS(lang).map(opt => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>
                      </div>

                      <div className="weight-row">
                        <span className={c.weight >= 0 ? 'positive' : 'negative'}>
                          {c.weight > 0 ? '+' : ''}{(c.weight * 100).toFixed(0)}%
                        </span>
                        <input
                          type="range"
                          min="-1"
                          max="1"
                          step="0.1"
                          value={c.weight}
                          onChange={(e) => updateComponent(c.id, 'weight', parseFloat(e.target.value))}
                        />
                      </div>
                    </div>
                  ))}
                </div>

                <button
                  className="calculate-btn"
                  onClick={calculateCustomIndex}
                  disabled={loading}
                >
                  {loading ? t.calculating : t.calculate}
                </button>
              </>
            )}
          </div>
        )}

        {/* Active Index Controls */}
        {indexResult && (
          <div className="section active-index">
            <div className="index-header">
              <h3>{indexResult.name}</h3>
              <button className="clear-btn" onClick={clearIndex}>×</button>
            </div>

            <div className="toggle-group">
              <label>
                <input
                  type="checkbox"
                  checked={showOverlay}
                  onChange={(e) => setShowOverlay(e.target.checked)}
                />
                {t.colorOverlay}
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={showDataPoints}
                  onChange={(e) => setShowDataPoints(e.target.checked)}
                />
                {t.dataPoints}
              </label>
            </div>

            {indexResult.skipped_components && indexResult.skipped_components.length > 0 && (
              <div className="skipped-warning">
                <strong>{lang === 'de' ? 'Übersprungen:' : 'Skipped:'}</strong>
                {indexResult.skipped_components.map((s, i) => (
                  <div key={i} className="skipped-item">
                    {s.label} <span className="skipped-reason">({s.reason})</span>
                  </div>
                ))}
              </div>
            )}

            {indexResult.components && indexResult.components.length > 0 && (
              <button className="edit-index-btn" onClick={editCurrentIndex}>
                {t.editIndex}
              </button>
            )}
          </div>
        )}

        {/* Selected District Breakdown */}
        {selectedDistrict && (
          <div className="district-detail">
            <div className="district-header">
              <h3>{selectedDistrict.name}</h3>
              <span className="district-score">{selectedDistrict.score?.toFixed(0)}</span>
            </div>

            <div className="breakdown-list">
              {selectedDistrict.breakdown.map((item, i) => {
                const normLabel = t.normalization[item.normalize] || item.normalize;
                const aggLabel = t.aggregation[item.aggregation] || item.aggregation;

                return (
                  <div key={i} className="breakdown-item">
                    <div className="breakdown-row">
                      <span className="breakdown-label">
                        {item.label}
                        {item.description && (
                          <Tooltip text={item.description}>
                            <span className="info-icon">ⓘ</span>
                          </Tooltip>
                        )}
                      </span>
                      <span className={`breakdown-weight ${item.weight < 0 ? 'negative' : 'positive'}`}>
                        {item.weight > 0 ? '+' : ''}{(item.weight * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="breakdown-meta">
                      {aggLabel} · {normLabel} · <span className="raw-value">
                        {item.count ?? '?'}
                        {item.denominator != null && (
                          <>/{item.normalize === 'population'
                            ? `${Math.round(item.denominator / 1000)}k ${lang === 'de' ? 'Einw.' : 'res.'}`
                            : `${item.denominator.toFixed(1)} km²`
                          }</>
                        )}
                      </span>
                    </div>
                    <div className="breakdown-bar-container">
                      <div
                        className={`breakdown-bar ${item.weight < 0 ? 'negative' : 'positive'}`}
                        style={{ width: `${item.value}%` }}
                      />
                    </div>
                    <div className="breakdown-value">{item.value.toFixed(0)}/100</div>
                  </div>
                );
              })}
            </div>

            <button className="close-detail" onClick={() => setSelectedDistrict(null)}>
              {t.close}
            </button>
          </div>
        )}

        {loading && (
          <div className="loading">
            <div className="spinner" />
          </div>
        )}
      </div>

      {/* Map */}
      <div className="map-wrapper">
        <MapView
          results={showDataPoints ? mapFeatures : []}
          datasetMetadata={datasetMetadata}
          showDistricts={true}
          districtData={showOverlay ? districtData : null}
          onDistrictClick={indexResult ? handleDistrictClick : null}
        />
        <Chatbot
          onIndexResult={applyIndexResult}
          onGeoData={handleChatGeoData}
        />
      </div>
    </div>
  );
}

export default App;
