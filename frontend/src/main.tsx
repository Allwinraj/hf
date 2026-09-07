import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AgentProvider } from './context/AgentContext'
import { ThemeProvider } from './context/ThemeContext'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <AgentProvider>
          <App />
        </AgentProvider>
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
)
