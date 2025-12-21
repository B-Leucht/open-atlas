import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import MapView from './components/MapView';
import './App.css';

const API_URL = `http://${window.location.hostname}:5001/api`;

function App() {
  const [stats, setStats] = useState(null);

  // Dataset selection
  const [datasetSearch, setDatasetSearch] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [selectedDatasets, setSelectedDatasets] = useState([]);

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [datasetMetadata, setDatasetMetadata] = useState({});
  const [loading, setLoading] = useState(false);

  // View
  const [viewMode, setViewMode] = useState('map');
  const [displayLimit, setDisplayLimit] = useState(20);

  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      const response = await axios.get(`${API_URL}/stats`);
      setStats(response.data);
    } catch (error) {
      console.error('Error loading stats:', error);
    }
  };

  const searchDatasets = async (query) => {
    if (query.length < 2) {
      setSuggestions([]);
      return;
    }
    try {
      const response = await axios.get(`${API_URL}/datasets/search`, { params: { q: query } });
      setSuggestions(response.data.suggestions);
    } catch (error) {
      console.error('Error searching datasets:', error);
    }
  };

  const addDataset = (dataset) => {
    if (!selectedDatasets.find(d => d.id === dataset.id)) {
      setSelectedDatasets([...selectedDatasets, dataset]);
    }
    setDatasetSearch('');
    setSuggestions([]);
  };

  const removeDataset = (datasetId) => {
    setSelectedDatasets(selectedDatasets.filter(d => d.id !== datasetId));
  };

  const performSearch = useCallback(async () => {
    if (selectedDatasets.length === 0) {
      setSearchResults([]);
      return;
    }

    setLoading(true);
    setDisplayLimit(20);

    try {
      const params = new URLSearchParams();
      params.append('q', searchQuery);
      selectedDatasets.forEach(d => params.append('datasets', d.id));

      const response = await axios.get(`${API_URL}/search?${params.toString()}`);
      setSearchResults(response.data.results || []);
      setDatasetMetadata(response.data.dataset_metadata || {});

      const hasGeodata = (response.data.results || []).some(r => r.geometry?.coordinates);
      setViewMode(hasGeodata ? 'map' : 'list');
    } catch (error) {
      console.error('Error searching:', error);
      setSearchResults([]);
    } finally {
      setLoading(false);
    }
  }, [selectedDatasets, searchQuery]);

  useEffect(() => {
    if (selectedDatasets.length > 0) {
      const timer = setTimeout(performSearch, 300);
      return () => clearTimeout(timer);
    }
  }, [searchQuery, selectedDatasets, performSearch]);

  const mapResults = searchResults.map(result => ({
    ...result,
    category: result.dataset_id || 'unknown'
  }));

  return (
    <div className="app">
      <header className="header">
        <h1>Munich Open Data</h1>
        {stats && <span className="stat">{stats.total_datasets} datasets available</span>}
      </header>

      <div className="controls">
        <div className="dataset-picker">
          <input
            type="text"
            placeholder="Add datasets to search..."
            value={datasetSearch}
            onChange={(e) => {
              setDatasetSearch(e.target.value);
              searchDatasets(e.target.value);
            }}
          />
          {suggestions.length > 0 && (
            <div className="dropdown">
              {suggestions.map(dataset => (
                <div key={dataset.id} className="dropdown-item" onClick={() => addDataset(dataset)}>
                  {dataset.title}
                </div>
              ))}
            </div>
          )}
        </div>

        {selectedDatasets.length > 0 && (
          <div className="chips">
            {selectedDatasets.map(dataset => (
              <span key={dataset.id} className="chip">
                {dataset.title}
                <button onClick={() => removeDataset(dataset.id)}>&times;</button>
              </span>
            ))}
          </div>
        )}

        {selectedDatasets.length > 0 && (
          <div className="search-row">
            <input
              type="text"
              className="search-input"
              placeholder="Search within selected datasets..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <div className="view-toggle">
              <button className={viewMode === 'list' ? 'active' : ''} onClick={() => setViewMode('list')}>List</button>
              <button className={viewMode === 'map' ? 'active' : ''} onClick={() => setViewMode('map')}>Map</button>
            </div>
          </div>
        )}
      </div>

      <main className="content">
        {selectedDatasets.length === 0 ? (
          <div className="empty">
            <p>Search and add datasets above to get started</p>
          </div>
        ) : loading ? (
          <div className="loading">Loading...</div>
        ) : viewMode === 'map' ? (
          <MapView results={mapResults} datasetMetadata={datasetMetadata} />
        ) : (
          <div className="results">
            <div className="results-count">
              {searchResults.length} results
              {searchResults.length > displayLimit && ` (showing ${displayLimit})`}
            </div>
            <div className="results-list">
              {searchResults.slice(0, displayLimit).map((result, idx) => {
                const meta = datasetMetadata[result.dataset_id];
                const filteredProps = Object.entries(result.properties || {})
                  .filter(([key, value]) => {
                    if (!value) return false;
                    const k = key.toLowerCase();
                    if (k.includes('objectid') || k.includes('shape') || k.includes('coord') || k.includes('geometry') || k.includes('fid')) return false;
                    if (String(value).length > 200) return false;
                    return true;
                  })
                  .slice(0, 6);

                return (
                  <div key={idx} className="result-card">
                    <div className="result-source">{meta?.title || result.dataset_id}</div>
                    <div className="result-props">
                      {filteredProps.map(([key, value]) => (
                        <div key={key} className="prop">
                          <span className="prop-key">{key.replace(/_/g, ' ')}:</span>
                          <span className="prop-value">{String(value)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
            {searchResults.length > displayLimit && (
              <button className="load-more" onClick={() => setDisplayLimit(prev => prev + 20)}>
                Load more ({searchResults.length - displayLimit} remaining)
              </button>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
