import React from 'react';
import './CategoryFilter.css';

function CategoryFilter({ categories, selectedCategories, toggleCategory, clearCategories }) {
  return (
    <div className="category-filter">
      <div className="category-header">
        <label>Filter by category:</label>
        {selectedCategories.length > 0 && (
          <button className="clear-filters-btn" onClick={clearCategories}>
            Clear all ({selectedCategories.length})
          </button>
        )}
      </div>
      <div className="category-buttons">
        {categories.map((cat) => (
          <button
            key={cat.id}
            className={selectedCategories.includes(cat.id) ? 'active' : ''}
            onClick={() => toggleCategory(cat.id)}
          >
            {selectedCategories.includes(cat.id) && '✓ '}
            {cat.name} ({cat.count})
          </button>
        ))}
      </div>
    </div>
  );
}

export default CategoryFilter;
