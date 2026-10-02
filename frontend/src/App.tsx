import { NavLink, Route, Routes } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Fleet from './pages/Fleet';
import VehicleDetail from './pages/VehicleDetail';
import RoutesPage from './pages/RoutesPage';
import Deliveries from './pages/Deliveries';
import Anomalies from './pages/Anomalies';
import Predictions from './pages/Predictions';
import Models from './pages/Models';
import HealthBadge from './components/HealthBadge';

const nav = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/fleet', label: 'Fleet' },
  { to: '/routes', label: 'Routes' },
  { to: '/deliveries', label: 'Deliveries' },
  { to: '/anomalies', label: 'Anomalies' },
  { to: '/predictions', label: 'Predictions' },
  { to: '/models', label: 'Models' },
];

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="bg-brand-900 text-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <div>
            <h1 className="text-xl font-bold tracking-tight">FleetIQ</h1>
            <p className="text-xs text-brand-100">Real-Time Supply Chain Intelligence</p>
          </div>
          <HealthBadge />
        </div>
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-2">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `whitespace-nowrap rounded px-3 py-1.5 text-sm font-medium ${
                  isActive ? 'bg-white/15 text-white' : 'text-brand-100 hover:bg-white/10'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/fleet" element={<Fleet />} />
          <Route path="/fleet/:vehicleId" element={<VehicleDetail />} />
          <Route path="/routes" element={<RoutesPage />} />
          <Route path="/deliveries" element={<Deliveries />} />
          <Route path="/anomalies" element={<Anomalies />} />
          <Route path="/predictions" element={<Predictions />} />
          <Route path="/models" element={<Models />} />
        </Routes>
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-6 text-xs text-slate-500">
        FleetIQ — all data is synthetic and generated locally. Not real logistics data.
      </footer>
    </div>
  );
}
