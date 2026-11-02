import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './app/App'
import { StudioProvider } from './app/state'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><StudioProvider><App /></StudioProvider></React.StrictMode>,
)
