import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import './Tooltip.css';

// Parse text and convert links to clickable elements
function parseLinks(text) {
  if (!text) return null;

  const parts = [];
  let key = 0;

  // Combined regex to match all link types (including relative paths in markdown)
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)|<a[^>]*href=["']?([^"'\s>]+)["']?[^>]*>([^<]*)<\/a>|(https?:\/\/[^\s<>)"]+|www\.[^\s<>)"]+)/gi;

  let lastIndex = 0;
  let match;

  while ((match = linkRegex.exec(text)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      parts.push(<span key={key++}>{text.substring(lastIndex, match.index)}</span>);
    }

    let url, linkText;

    if (match[1] && match[2]) {
      // Markdown link: [text](url)
      linkText = match[1];
      url = match[2];
    } else if (match[3]) {
      // HTML link: <a href="url">text</a>
      url = match[3];
      linkText = match[4] || url;
    } else if (match[5]) {
      // Raw URL
      url = match[5];
      linkText = url.length > 50 ? url.substring(0, 50) + '...' : url;
    }

    // Ensure URL has protocol
    if (url) {
      if (url.startsWith('/')) {
        // Relative path - prepend opendata.muenchen.de
        url = 'https://opendata.muenchen.de' + url;
      } else if (!url.startsWith('http') && !url.startsWith('mailto:')) {
        url = 'https://' + url;
      }
    }

    if (url) {
      parts.push(
        <a
          key={key++}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="tooltip-link"
          onClick={(e) => e.stopPropagation()}
        >
          {linkText}
        </a>
      );
    }

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(<span key={key++}>{text.substring(lastIndex)}</span>);
  }

  return parts.length > 0 ? parts : text;
}

function Tooltip({ text, children }) {
  const [visible, setVisible] = useState(false);

  if (!text) return children;

  const handleClick = (e) => {
    e.stopPropagation();
    setVisible(!visible);
  };

  const handleClose = () => {
    setVisible(false);
  };

  return (
    <>
      <span className="tooltip-trigger" onClick={handleClick}>
        {children}
      </span>
      {visible && ReactDOM.createPortal(
        <div className="tooltip-overlay" onClick={handleClose}>
          <div className="tooltip-content" onClick={(e) => e.stopPropagation()}>
            {parseLinks(text)}
          </div>
        </div>,
        document.body
      )}
    </>
  );
}

export default Tooltip;
