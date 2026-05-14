import { NavLink } from 'react-router-dom'
import './Navbar.css'

export default function Navbar() {
  return (
    <nav className="navbar">
      <NavLink to="/games" className="logo">
        <div className="logo-mark">SR</div>
        <div className="logo-text">Snap<span>Recap</span></div>
      </NavLink>
      <div className="nav-right">
        <NavLink
          to="/games"
          className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}
        >
          Games
        </NavLink>
        <NavLink
          to="/about"
          className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}
        >
          About
        </NavLink>
      </div>
    </nav>
  )
}
