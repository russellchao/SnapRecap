import './App.css'
import { Routes, Route, Navigate } from 'react-router-dom'

import Navbar from './components/Navbar'
import Games from './pages/Games'
import Recap from './pages/Recap'
import About from './pages/About'

function App() {
  return (
    <div className="App">
      <Navbar />
      <Routes>
        <Route path="/" element={<Navigate to="/games" />} /> {/* Set the default route to /games */}
        <Route path="/games" element={<Games />} />
        <Route path="/recap/:gameId" element={<Recap />} />
        <Route path="/about" element={<About />} />
        <Route path="*" element={<Navigate to="/games" />} /> {/* Redirect any unknown routes to /games */}
      </Routes>
    </div>
  )
}

export default App
