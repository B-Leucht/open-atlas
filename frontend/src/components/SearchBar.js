import React from 'react';
import './SearchBar.css';

function SearchBar({ query, setQuery }) {
  return (
    <div className="search-bar">
      <input
        type="text"
        placeholder="Search for markets, bike paths, parking, dangers..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="search-input"
      />
      {query && (
        <button onClick={() => setQuery('')} className="clear-button">
          Clear
        </button>
      )}
    </div>
  );
}

export default SearchBar;
