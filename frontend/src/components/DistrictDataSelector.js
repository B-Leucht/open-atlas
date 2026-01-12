import React, { useState, useEffect, useMemo } from 'react';
import './DistrictDataSelector.css';

const API_URL = `http://${window.location.hostname}:5001/api`;

function DistrictDataSelector({ onDataChange, onClose }) {
  const [allDatasets, setAllDatasets] = useState([]);
  const [searchResults, setSearchResults] = useState(null); // null = not searching, [] = no results
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedDataset, setSelectedDataset] = useState(null);
  const [columns, setColumns] = useState([]);
  const [selectedColumn, setSelectedColumn] = useState('');
  const [aggregation, setAggregation] = useState('count');
  const [districtData, setDistrictData] = useState(null);
  const [error, setError] = useState(null);
  const [dataLoading, setDataLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);

  // Load all datasets
  useEffect(() => {
    loadDatasets();
  }, []);

  // Debounced search when query or showAll changes
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }

    const timeoutId = setTimeout(() => {
      searchDatasets(searchQuery);
    }, 300); // 300ms debounce

    return () => clearTimeout(timeoutId);
  }, [searchQuery, showAll]);

  const loadDatasets = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_URL}/v2/datasets?limit=500`);
      const data = await response.json();

      if (data.success) {
        // Sort: district-specific first, then alphabetically
        const sorted = data.datasets.sort((a, b) => {
          const aDistrict = isDistrictDataset(a);
          const bDistrict = isDistrictDataset(b);
          if (aDistrict && !bDistrict) return -1;
          if (!aDistrict && bDistrict) return 1;
          return a.title.localeCompare(b.title);
        });
        setAllDatasets(sorted);
      }
    } catch (err) {
      setError('Failed to load datasets');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const searchDatasets = async (query) => {
    console.log('searchDatasets called with:', query);
    try {
      setSearchLoading(true);
      const params = new URLSearchParams({
        q: query,
        limit: '50'
      });

      const url = `${API_URL}/v2/datasets/search?${params}`;
      console.log('Fetching:', url);

      const response = await fetch(url);
      const data = await response.json();

      console.log('Response:', data.success, 'count:', data.count, 'datasets:', data.datasets?.length);

      if (data.success) {
        setSearchResults(data.datasets);
      } else {
        console.error('Search failed:', data.error);
        setSearchResults([]);
      }
    } catch (err) {
      console.error('Search error:', err);
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  };

  // Check if dataset is district-related
  const isDistrictDataset = (ds) => {
    const title = ds.title?.toLowerCase() || '';
    const desc = ds.description?.toLowerCase() || '';
    const tags = ds.tags?.map(t => t.toLowerCase()).join(' ') || '';
    const combined = `${title} ${desc} ${tags}`;

    return ds.is_district_specific ||
      combined.includes('stadtbezirk') ||
      combined.includes('bezirk') ||
      combined.includes('bevölkerung') ||
      combined.includes('einwohner') ||
      combined.includes('indikatorenatlas');
  };

  // Filter datasets based on search and showAll toggle
  const filteredDatasets = useMemo(() => {
    // If we have search results from backend, use those (already ranked by relevance)
    if (searchResults !== null) {
      return searchResults;
    }

    // Otherwise, filter the local dataset list
    let datasets = allDatasets;

    // If not showing all, only show district-related
    if (!showAll) {
      datasets = datasets.filter(isDistrictDataset);
    }

    return datasets;
  }, [allDatasets, searchResults, showAll]);

  const handleDatasetSelect = async (dataset) => {
    setSelectedDataset(dataset);
    setDistrictData(null);
    setError(null);

    // Try to get columns from a sample of the data
    try {
      const response = await fetch(
        `${API_URL}/v2/datasets/${dataset.id}/features?limit=1`
      );
      const data = await response.json();

      if (data.success && data.data?.features?.length > 0) {
        const props = data.data.features[0].properties || {};
        const numericColumns = Object.entries(props)
          .filter(([key, value]) => {
            if (key.toLowerCase().includes('objectid')) return false;
            if (key.toLowerCase().includes('id')) return false;
            const numVal = parseFloat(String(value).replace(',', '.'));
            return !isNaN(numVal);
          })
          .map(([key]) => key);

        setColumns(numericColumns);
        if (numericColumns.length > 0) {
          setSelectedColumn(numericColumns[0]);
        }
      } else {
        setColumns([]);
      }
    } catch (err) {
      console.error('Failed to get columns:', err);
      setColumns([]);
    }
  };

  const loadDistrictData = async () => {
    if (!selectedDataset) return;

    setDataLoading(true);
    setError(null);

    try {
      // Try with the dataset ID (could be internal id or external_id)
      const datasetIdentifier = selectedDataset.external_id || selectedDataset.id;

      const params = new URLSearchParams({
        dataset: datasetIdentifier,
        agg: aggregation
      });

      if (selectedColumn && aggregation !== 'count') {
        params.append('column', selectedColumn);
      }

      const response = await fetch(`${API_URL}/districts/aggregate?${params}`);
      const data = await response.json();

      if (data.success) {
        setDistrictData(data.data);
        onDataChange(data.data, {
          dataset: selectedDataset,
          column: selectedColumn,
          aggregation: aggregation
        });
      } else {
        setError(data.error || 'Failed to load district data');
      }
    } catch (err) {
      setError('Failed to load district data');
      console.error(err);
    } finally {
      setDataLoading(false);
    }
  };

  const clearData = () => {
    setDistrictData(null);
    setSelectedDataset(null);
    setColumns([]);
    setSelectedColumn('');
    onDataChange(null, null);
  };

  return (
    <div className="district-selector">
      <div className="district-selector-header">
        <h3>District Data Visualization</h3>
        <button className="close-btn" onClick={onClose}>&times;</button>
      </div>

      <div className="district-selector-content">
        {loading ? (
          <div className="loading-small">Loading datasets...</div>
        ) : (
          <>
            {/* Search and Filter */}
            <div className="selector-section">
              <div className="search-input-wrapper">
                <input
                  type="text"
                  className="dataset-search"
                  placeholder="Search datasets (semantic)..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {searchLoading && <span className="search-spinner">...</span>}
              </div>
              <label className="show-all-toggle">
                <input
                  type="checkbox"
                  checked={showAll}
                  onChange={(e) => setShowAll(e.target.checked)}
                />
                Show all datasets ({allDatasets.length})
              </label>
            </div>

            {/* Dataset Selection */}
            <div className="selector-section">
              <label>Select Dataset ({filteredDatasets.length} available):</label>
              <select
                value={selectedDataset?.id || ''}
                onChange={(e) => {
                  const ds = filteredDatasets.find(d => d.id === e.target.value);
                  if (ds) handleDatasetSelect(ds);
                }}
                size={6}
                className="dataset-list"
              >
                {filteredDatasets.map(ds => (
                  <option key={ds.id} value={ds.id} title={ds.description}>
                    {isDistrictDataset(ds) ? '📍 ' : ''}{ds.title}
                  </option>
                ))}
              </select>
            </div>

            {/* Aggregation Selection */}
            {selectedDataset && (
              <div className="selector-section">
                <label>Aggregation:</label>
                <div className="radio-group">
                  {['count', 'sum', 'avg', 'min', 'max'].map(agg => (
                    <label key={agg} className="radio-label">
                      <input
                        type="radio"
                        name="aggregation"
                        value={agg}
                        checked={aggregation === agg}
                        onChange={(e) => setAggregation(e.target.value)}
                      />
                      {agg.charAt(0).toUpperCase() + agg.slice(1)}
                    </label>
                  ))}
                </div>
              </div>
            )}

            {/* Column Selection (for non-count aggregations) */}
            {selectedDataset && aggregation !== 'count' && columns.length > 0 && (
              <div className="selector-section">
                <label>Value Column:</label>
                <select
                  value={selectedColumn}
                  onChange={(e) => setSelectedColumn(e.target.value)}
                >
                  {columns.map(col => (
                    <option key={col} value={col}>{col}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Action Buttons */}
            {selectedDataset && (
              <div className="selector-actions">
                <button
                  className="btn-primary"
                  onClick={loadDistrictData}
                  disabled={dataLoading}
                >
                  {dataLoading ? 'Loading...' : 'Show on Map'}
                </button>
                {districtData && (
                  <button className="btn-secondary" onClick={clearData}>
                    Clear
                  </button>
                )}
              </div>
            )}

            {/* Error Display */}
            {error && (
              <div className="selector-error">{error}</div>
            )}

            {/* Data Preview */}
            {districtData && Object.keys(districtData).length > 0 && (
              <div className="data-preview">
                <h4>Data by District:</h4>
                <div className="preview-grid">
                  {Object.entries(districtData)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([district, value]) => (
                      <div key={district} className="preview-item">
                        <span className="district-num">{district}</span>
                        <span className="district-value">
                          {typeof value === 'number' ? value.toLocaleString('de-DE', {
                            maximumFractionDigits: 2
                          }) : value}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default DistrictDataSelector;
