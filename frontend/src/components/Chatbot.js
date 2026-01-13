import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './Chatbot.css';

// Use the same API as the rest of the app
const API_BASE_URL = `http://${window.location.hostname}:5001/api`;

// Mock data for testing without API
const MOCK_INDEX_RESULT = {
  success: true,
  name: "Family Friendliness Index",
  districts: [
    { number: 1, name: "Altstadt-Lehel" },
    { number: 2, name: "Ludwigsvorstadt-Isarvorstadt" },
    { number: 3, name: "Maxvorstadt" },
    { number: 4, name: "Schwabing-West" },
    { number: 5, name: "Au-Haidhausen" },
    { number: 6, name: "Sendling" },
    { number: 7, name: "Sendling-Westpark" },
    { number: 8, name: "Schwanthalerhöhe" },
    { number: 9, name: "Neuhausen-Nymphenburg" },
    { number: 10, name: "Moosach" },
    { number: 11, name: "Milbertshofen-Am Hart" },
    { number: 12, name: "Schwabing-Freimann" },
    { number: 13, name: "Bogenhausen" },
    { number: 14, name: "Berg am Laim" },
    { number: 15, name: "Trudering-Riem" },
    { number: 16, name: "Ramersdorf-Perlach" },
    { number: 17, name: "Obergiesing-Fasangarten" },
    { number: 18, name: "Untergiesing-Harlaching" },
    { number: 19, name: "Thalkirchen-Obersendling-Forstenried-Fürstenried-Solln" },
    { number: 20, name: "Hadern" },
    { number: 21, name: "Pasing-Obermenzing" },
    { number: 22, name: "Aubing-Lochhausen-Langwied" },
    { number: 23, name: "Allach-Untermenzing" },
    { number: 24, name: "Feldmoching-Hasenbergl" },
    { number: 25, name: "Laim" }
  ],
  scores: {
    1: 42, 2: 38, 3: 55, 4: 68, 5: 61,
    6: 52, 7: 71, 8: 45, 9: 78, 10: 65,
    11: 48, 12: 72, 13: 82, 14: 58, 15: 85,
    16: 63, 17: 56, 18: 74, 19: 79, 20: 69,
    21: 76, 22: 88, 23: 73, 24: 54, 25: 59
  },
  stats: { min: 38, max: 88, avg: 64 },
  components: [
    { label: "Playgrounds", weight: 0.3, normalize: "population" },
    { label: "Schools", weight: 0.25, normalize: "population" },
    { label: "Green Spaces", weight: 0.2, normalize: "area" },
    { label: "Danger Zones", weight: -0.15, normalize: "population" }
  ],
  breakdown: {}
};

export default function Chatbot({ onIndexResult, onGeoData }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([
    { id: 1, text: "Hello! Ask me anything about Munich Open Data. Try asking 'Which district is best for families?' to see an index on the map!", sender: 'bot' }
  ]);
  const [sending, setSending] = useState(false);
  const [apiHealthy, setApiHealthy] = useState(null);

  const messagesRef = useRef(null);

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    checkHealth();
  }, []);

  const checkHealth = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/health`);
      if (response.ok) {
        setApiHealthy(true);
      } else {
        setApiHealthy(false);
      }
    } catch (error) {
      console.warn("Health check failed:", error);
      setApiHealthy(false);
    }
  };

  const send = async () => {
    if (!input.trim()) return;

    const userMessageText = input;
    const newUserMsg = { id: Date.now(), text: userMessageText, sender: 'user' };
    setMessages(prev => [...prev, newUserMsg]);
    setInput('');
    setSending(true);

    try {
      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: userMessageText
        }),
      });

      const data = await response.json();

      if (data.success) {
        // Build message with optional visualization indicator
        let messageText = data.answer;
        let hasVisualization = false;

        // Handle index result - display on map
        if (data.index_result && onIndexResult) {
          onIndexResult(data.index_result, data.suggested_index);
          hasVisualization = true;
        }

        // Handle geographic data - display points on map
        if (data.geo_data && onGeoData) {
          onGeoData(data.geo_data);
          hasVisualization = true;
        }

        const newBotMsg = {
          id: Date.now() + 1,
          text: messageText,
          sender: 'bot',
          hasVisualization,
          queryType: data.query_type
        };
        setMessages(prev => [...prev, newBotMsg]);
      } else {
        const errorMsg = { id: Date.now() + 1, text: data.error || "Something went wrong.", sender: 'bot' };
        setMessages(prev => [...prev, errorMsg]);
      }
    } catch (error) {
      console.error("Query failed:", error);
      const errorMsg = { id: Date.now() + 1, text: "Sorry, I'm having trouble connecting to the server.", sender: 'bot' };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  // Test function to simulate index result without API
  const testIndexDisplay = () => {
    if (onIndexResult) {
      onIndexResult(MOCK_INDEX_RESULT, { name: "Family Friendliness Index (Test)" });
      const testMsg = {
        id: Date.now(),
        text: "🧪 TEST: Displaying mock Family Friendliness Index on the map. Districts are colored by score (38-88 range). Aubing-Lochhausen-Langwied scores highest (88), Ludwigsvorstadt-Isarvorstadt lowest (38).",
        sender: 'bot',
        hasVisualization: true,
        queryType: 'index_creation'
      };
      setMessages(prev => [...prev, testMsg]);
    }
  };

  return (
    <div className="chatbot">
      {open && (
        <div className="chat-window" role="dialog" aria-label="Chatbot window">
          <div className="chat-header">
            <div className="chat-title">Data Assistant</div>
            <div className="chat-status">
              {apiHealthy === null ? 'Checking...' : apiHealthy ? 'Connected' : 'Offline'}
            </div>
            <button className="chat-close" onClick={() => setOpen(false)} aria-label="Close chat">×</button>
          </div>

          <div className="chat-messages" ref={messagesRef}>
            {messages.map(m => (
              <div key={m.id} className={`chat-message ${m.sender}`}>
                <div className="chat-bubble">
                  {m.sender === 'bot' ? (
                    <div className="markdown-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                    </div>
                  ) : (
                    m.text
                  )}
                  {m.hasVisualization && (
                    <div className="visualization-indicator">
                      {m.queryType === 'index_creation' ? '📊 Index shown on map' : '📍 Data shown on map'}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {sending && (
              <div className="chat-message bot">
                <div className="chat-bubble typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            )}
          </div>

          <div className="chat-input">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about Munich data..."
              rows={1}
            />
            <button className="chat-send" onClick={send} disabled={sending || !input.trim()}>
              {sending ? '...' : 'Send'}
            </button>
            <button className="chat-test" onClick={testIndexDisplay} title="Test index display">
              🧪
            </button>
          </div>
        </div>
      )}

      <button className="chat-toggle" onClick={async () => {
        if (!open) await checkHealth();
        setOpen(o => !o);
      }} aria-label="Open chat">
        💬
      </button>
    </div>
  );
}
