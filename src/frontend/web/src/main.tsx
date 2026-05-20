import React from 'react';
import ReactDOM from 'react-dom/client';
import './styles/theme.css';
import './styles/modules.css';
import App from './App';
import { installAuthFetchInterceptor } from './services/auth';

installAuthFetchInterceptor();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
