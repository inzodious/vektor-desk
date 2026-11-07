import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import '@fontsource/bebas-neue/400.css';
import '@fontsource-variable/league-spartan';
import '@fontsource-variable/dm-sans';
import './styles/tokens.css';
import './styles/desk.css';
import App from './App.jsx';
import { applyTheme, readTheme } from './lib/theme.js';

applyTheme(readTheme(), !new URLSearchParams(window.location.search).has('theme'));

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
