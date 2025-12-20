import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import MapView from './components/MapView';
import './App.css';

const API_URL = `http://${window.location.hostname}:5001/api`;

function App() {
  // Workspace management
  const [workspaces, setWorkspaces] = useState([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState(null);
  const [showCreateWorkspace, setShowCreateWorkspace] = useState(false);

  // Dataset search for workspace creation
  const [datasetSearch, setDatasetSearch] = useState('');
  const [datasetSuggestions, setDatasetSuggestions] = useState([]);
  const [selectedDatasets, setSelectedDatasets] = useState([]);
  const [newWorkspaceName, setNewWorkspaceName] = useState('');
  const [newWorkspaceDesc, setNewWorkspaceDesc] = useState('');

  // Search within workspace
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState(null);
  const [datasetMetadata, setDatasetMetadata] = useState({});

  // UI state
  const [viewMode, setViewMode] = useState('list'); // 'list' or 'map'
  const [sidebarVisible, setSidebarVisible] = useState(true);

  useEffect(() => {
    loadWorkspaces();
    loadStats();
  }, []);

  const loadWorkspaces = async () => {
    try {
      const response = await axios.get(`${API_URL}/workspaces`);
      setWorkspaces(response.data.workspaces);
    } catch (error) {
      console.error('Error loading workspaces:', error);
    }
  };

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
      setDatasetSuggestions([]);
      return;
    }

    try {
      const response = await axios.get(`${API_URL}/datasets/search`, {
        params: { q: query }
      });
      setDatasetSuggestions(response.data.suggestions);
    } catch (error) {
      console.error('Error searching datasets:', error);
    }
  };

  const addDataset = (dataset) => {
    if (!selectedDatasets.find(d => d.id === dataset.id)) {
      setSelectedDatasets([...selectedDatasets, dataset]);
    }
    setDatasetSearch('');
    setDatasetSuggestions([]);
  };

  const removeDataset = (datasetId) => {
    setSelectedDatasets(selectedDatasets.filter(d => d.id !== datasetId));
  };

  const createWorkspace = async () => {
    if (!newWorkspaceName || selectedDatasets.length === 0) {
      alert('Please provide a workspace name and select at least one dataset');
      return;
    }

    try {
      const response = await axios.post(`${API_URL}/workspaces`, {
        name: newWorkspaceName,
        description: newWorkspaceDesc,
        dataset_ids: selectedDatasets.map(d => d.id)
      });

      setWorkspaces([response.data, ...workspaces]);
      setSelectedWorkspace(response.data);
      setShowCreateWorkspace(false);
      setNewWorkspaceName('');
      setNewWorkspaceDesc('');
      setSelectedDatasets([]);
    } catch (error) {
      console.error('Error creating workspace:', error);
      alert('Error creating workspace');
    }
  };

  const deleteWorkspace = async (workspaceId) => {
    if (!window.confirm('Delete this workspace?')) return;

    try {
      await axios.delete(`${API_URL}/workspaces/${workspaceId}`);
      setWorkspaces(workspaces.filter(w => w.id !== workspaceId));
      if (selectedWorkspace?.id === workspaceId) {
        setSelectedWorkspace(null);
        setSearchResults([]);
      }
    } catch (error) {
      console.error('Error deleting workspace:', error);
    }
  };

  const searchInWorkspace = useCallback(async () => {
    if (!selectedWorkspace) return;

    setLoading(true);
    try {
      const response = await axios.get(
        `${API_URL}/workspaces/${selectedWorkspace.id}/search`,
        { params: { q: searchQuery } }
      );
      const results = response.data.results;
      setSearchResults(results);
      setDatasetMetadata(response.data.dataset_metadata || {});

      // Auto-switch to map view if geodata is available
      const hasGeodata = results.some(r => r.geometry && r.geometry.coordinates);
      if (hasGeodata) {
        setViewMode('map');
      } else {
        setViewMode('list');
      }
    } catch (error) {
      console.error('Error searching workspace:', error);
      setSearchResults([]);
      setDatasetMetadata({});
    } finally {
      setLoading(false);
    }
  }, [selectedWorkspace, searchQuery]);

  useEffect(() => {
    if (selectedWorkspace && searchQuery !== undefined) {
      const timer = setTimeout(searchInWorkspace, 300);
      return () => clearTimeout(timer);
    }
  }, [searchQuery, selectedWorkspace, searchInWorkspace]);

  // Prepare results for MapView (add category field from dataset_id)
  const mapResults = searchResults.map(result => ({
    ...result,
    category: result.dataset_id || 'unknown'
  }));

  // Generate color from string hash (same as MapView)
  const stringToColor = (str) => {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash % 360);
    const saturation = 65 + (Math.abs(hash >> 8) % 20);
    const lightness = 45 + (Math.abs(hash >> 16) % 15);
    return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
  };

  // Group results by dataset for legend
  const datasetGroups = searchResults.reduce((acc, result) => {
    const datasetId = result.dataset_id || 'unknown';
    if (!acc[datasetId]) {
      acc[datasetId] = { count: 0, hasGeo: false };
    }
    acc[datasetId].count++;
    if (result.geometry && result.geometry.coordinates) {
      acc[datasetId].hasGeo = true;
    }
    return acc;
  }, {});

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-content">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarVisible(!sidebarVisible)}
            title={sidebarVisible ? 'Hide sidebar' : 'Show sidebar'}
          >
            {sidebarVisible ? '◀' : '▶'}
          </button>
          <h1>Munich Open Data</h1>
          {stats && (
            <div className="stats">
              {stats.total_datasets} datasets · {stats.total_workspaces} workspaces
            </div>
          )}
        </div>
      </header>

      <div className="app-content">
        {/* Sidebar */}
        <aside className={`sidebar ${!sidebarVisible ? 'hidden' : ''}`}>
          <div className="sidebar-header">
            <h2>Workspaces</h2>
            <button onClick={() => setShowCreateWorkspace(!showCreateWorkspace)}>
              {showCreateWorkspace ? '✕' : '+'}
            </button>
          </div>

          {showCreateWorkspace && (
            <div className="create-workspace">
              <input
                type="text"
                placeholder="Workspace name"
                value={newWorkspaceName}
                onChange={(e) => setNewWorkspaceName(e.target.value)}
              />
              <textarea
                placeholder="Description (optional)"
                value={newWorkspaceDesc}
                onChange={(e) => setNewWorkspaceDesc(e.target.value)}
                rows={2}
              />

              <div className="dataset-search">
                <input
                  type="text"
                  placeholder="Search datasets..."
                  value={datasetSearch}
                  onChange={(e) => {
                    setDatasetSearch(e.target.value);
                    searchDatasets(e.target.value);
                  }}
                />
                {datasetSuggestions.length > 0 && (
                  <div className="suggestions">
                    {datasetSuggestions.map(dataset => (
                      <div
                        key={dataset.id}
                        className="suggestion"
                        onClick={() => addDataset(dataset)}
                      >
                        {dataset.title}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {selectedDatasets.length > 0 && (
                <div className="selected-datasets">
                  {selectedDatasets.map(dataset => (
                    <div key={dataset.id} className="dataset-chip">
                      {dataset.title}
                      <button onClick={() => removeDataset(dataset.id)}>✕</button>
                    </div>
                  ))}
                </div>
              )}

              <button className="create-btn" onClick={createWorkspace}>
                Create Workspace
              </button>
            </div>
          )}

          <div className="workspace-list">
            {workspaces.map(workspace => (
              <div
                key={workspace.id}
                className={`workspace-item ${selectedWorkspace?.id === workspace.id ? 'active' : ''}`}
              >
                <div
                  className="workspace-info"
                  onClick={() => {
                    setSelectedWorkspace(workspace);
                    setSearchResults([]);
                    setSearchQuery('');
                  }}
                >
                  <div className="workspace-name">{workspace.name}</div>
                  <div className="workspace-meta">
                    {workspace.dataset_ids.length} dataset{workspace.dataset_ids.length !== 1 ? 's' : ''}
                  </div>
                </div>
                <button
                  className="delete-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteWorkspace(workspace.id);
                  }}
                >
                  🗑
                </button>
              </div>
            ))}
          </div>
        </aside>

        {/* Main content */}
        <main className="main-content">
          {selectedWorkspace ? (
            <>
              <div className="search-section">
                <div className="search-header">
                  <h2>{selectedWorkspace.name}</h2>
                  <div className="view-toggle">
                    <button
                      className={viewMode === 'list' ? 'active' : ''}
                      onClick={() => setViewMode('list')}
                    >
                      List
                    </button>
                    <button
                      className={viewMode === 'map' ? 'active' : ''}
                      onClick={() => setViewMode('map')}
                    >
                      Map
                    </button>
                  </div>
                </div>
                {selectedWorkspace.description && (
                  <p className="workspace-description">{selectedWorkspace.description}</p>
                )}
                <input
                  type="text"
                  className="search-input"
                  placeholder="Search within workspace..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>

              {loading ? (
                <div className="loading">Loading...</div>
              ) : viewMode === 'map' ? (
                <div className="map-container-wrapper">
                  <MapView results={mapResults} />
                  {Object.keys(datasetGroups).length > 0 && (
                    <div className="map-legend">
                      <div className="legend-header">Data Sources</div>
                      <div className="legend-content">
                        {Object.entries(datasetGroups).map(([datasetId, info]) => {
                          const metadata = datasetMetadata[datasetId];
                          const displayName = metadata?.title || datasetId.substring(0, 12) + '...';
                          const color = stringToColor(datasetId);
                          return (
                            <div key={datasetId} className="legend-item">
                              <div
                                className="legend-color"
                                style={{ backgroundColor: color }}
                                title={`Color for ${metadata?.title || datasetId}`}
                              />
                              <div className="legend-dataset" title={metadata?.title || datasetId}>
                                {displayName}
                              </div>
                              <div className="legend-stats">
                                {info.count} item{info.count !== 1 ? 's' : ''}
                                {info.hasGeo && ' 📍'}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                      <div className="legend-footer">
                        {searchResults.length} total result{searchResults.length !== 1 ? 's' : ''}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="results">
                  <div className="results-header">
                    {searchResults.length} result{searchResults.length !== 1 ? 's' : ''}
                  </div>
                  <div className="results-list">
                    {searchResults.map((result, idx) => (
                      <div key={idx} className="result-item">
                        <div className="result-properties">
                          {Object.entries(result.properties || {}).map(([key, value]) => (
                            <div key={key} className="property">
                              <span className="property-key">{key}:</span>
                              <span className="property-value">{String(value)}</span>
                            </div>
                          ))}
                        </div>
                        {result.distance_km && (
                          <div className="result-distance">{result.distance_km} km</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">
              <h2>Welcome to Munich Open Data</h2>
              <p>Select a workspace or create a new one to get started</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;