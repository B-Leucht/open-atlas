import './MobileBottomNav.css';

export default function MobileBottomNav({
  activeTab,
  onTabChange,
  hasActiveIndex = false,
  lang = 'en'
}) {
  const tabs = [
    { id: 'map', icon: '🗺️', label: lang === 'de' ? 'Karte' : 'Map' },
    { id: 'menu', icon: '☰', label: lang === 'de' ? 'Menü' : 'Menu' },
    { id: 'chat', icon: '💬', label: 'Chat' }
  ];

  return (
    <nav className="mobile-bottom-nav" aria-label="Main navigation">
      {tabs.map(tab => (
        <button
          key={tab.id}
          className={`nav-tab ${activeTab === tab.id ? 'active' : ''}`}
          onClick={() => onTabChange(tab.id)}
          aria-current={activeTab === tab.id ? 'page' : undefined}
        >
          <span className="nav-icon">{tab.icon}</span>
          <span className="nav-label">{tab.label}</span>
          {tab.id === 'menu' && hasActiveIndex && (
            <span className="nav-indicator" aria-label="Index active" />
          )}
        </button>
      ))}
    </nav>
  );
}
