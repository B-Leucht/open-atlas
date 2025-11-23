import React, { useState, useEffect } from 'react';
import axios from 'axios';
import SearchBar from './components/SearchBar';
import CategoryFilter from './components/CategoryFilter';
import ResultsList from './components/ResultsList';
import MapView from './components/MapView';
import Stats from './components/Stats';
import './App.css';

const API_URL = 'http://localhost:5000/api';

function App() {
  const [query, setQuery] = useState('');
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [results, setResults] = useState([]);
  const [categories, setCategories] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState('list'); // 'list' or 'map'
  const [mapCenter, setMapCenter] = useState([48.1351, 11.5820]); // Munich center
  const [showCategories, setShowCategories] = useState(false);

  useEffect(() => {
    loadCategories();
    loadStats();
  }, []);

  useEffect(() => {
    performSearch();
  }, [query, selectedCategories]);

  const loadCategories = async () => {
    try {
      console.log('Loading categories from:', `${API_URL}/categories`);
      const response = await axios.get(`${API_URL}/categories`);
      console.log('Categories loaded:', response.data.categories);
      setCategories(response.data.categories);
    } catch (error) {
      console.error('Error loading categories:', error);
      console.error('Error details:', error.response || error.message);
    }
  };

  const loadStats = async () => {
    try {
      console.log('Loading stats from:', `${API_URL}/stats`);
      const response = await axios.get(`${API_URL}/stats`);
      console.log('Stats loaded:', response.data);
      setStats(response.data);
    } catch (error) {
      console.error('Error loading stats:', error);
      console.error('Error details:', error.response || error.message);
    }
  };

  const performSearch = async () => {
    setLoading(true);
    try {
      // If no categories selected, show no results
      if (selectedCategories.length === 0) {
        console.log('No categories selected, showing no results');
        setResults([]);
        setLoading(false);
        return;
      }

      const categoryParam = selectedCategories.join(',');
      console.log('Searching with params:', { q: query, categories: categoryParam, lat: mapCenter[0], lon: mapCenter[1] });
      const response = await axios.get(`${API_URL}/search`, {
        params: {
          q: query,
          categories: categoryParam,
          lat: mapCenter[0],
          lon: mapCenter[1]
        }
      });
      console.log('Search results:', response.data);
      setResults(response.data.results || []);
    } catch (error) {
      console.error('Error searching:', error);
      console.error('Error details:', error.response || error.message);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const toggleCategory = (categoryId) => {
    setSelectedCategories(prev =>
      prev.includes(categoryId)
        ? prev.filter(c => c !== categoryId)
        : [...prev, categoryId]
    );
  };

  const clearCategories = () => {
    setSelectedCategories([]);
  };

  return (
    <div className="App">
      <div className={`top-bar ${showCategories ? 'expanded' : 'compact'}`}>
        <div className="search-bar-container">
          <SearchBar query={query} setQuery={setQuery} />
        </div>
        {showCategories && (
          <CategoryFilter
            categories={categories}
            selectedCategories={selectedCategories}
            toggleCategory={toggleCategory}
            clearCategories={clearCategories}
          />
        )}
        <div className="controls">
          {stats && <div className="stats-inline">{results.length} results</div>}
          <button
            className="category-toggle-btn"
            onClick={() => setShowCategories(!showCategories)}
            title={showCategories ? "Hide categories" : "Show categories"}
          >
            {showCategories ? '✕ Categories' : '☰ Categories'}
          </button>
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
      </div>

      <div className="main-content">
        {loading ? (
          <div className="loading">Loading...</div>
        ) : results.length === 0 ? (
          <div className="loading">
            <h3>No results found</h3>
            <p>{selectedCategories.length === 0 ? 'Select one or more categories to view data' : 'Try searching or selecting a different category'}</p>
            {selectedCategories.length > 0 && (
              <p style={{ fontSize: '0.85rem', color: '#999', marginTop: '1rem' }}>
                Backend: {API_URL}<br/>
                Query: "{query}"<br/>
                Categories: {selectedCategories.join(', ')}<br/>
                Check browser console for errors
              </p>
            )}
          </div>
        ) : (
          <>
            {viewMode === 'list' ? (
              <ResultsList results={results} />
            ) : (
              <MapView results={results} onMapMove={setMapCenter} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default App;
