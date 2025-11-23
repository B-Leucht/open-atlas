import React from 'react';
import './Stats.css';

function Stats({ stats, resultCount }) {
  return (
    <div className="stats">
      <div className="stat-card">
        <div className="stat-value">{resultCount}</div>
        <div className="stat-label">Results Displayed</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{stats.total_features}</div>
        <div className="stat-label">Total Data Points</div>
      </div>
      <div className="stat-card">
        <div className="stat-value">{stats.data_sources}</div>
        <div className="stat-label">Data Sources</div>
      </div>
    </div>
  );
}

export default Stats;
