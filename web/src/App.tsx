import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom';
import { ProtectedRoute } from './components/ProtectedRoute';
import { LoginPage } from './pages/LoginPage';
import { WatchlistPage } from './pages/WatchlistPage';
import './styles/app.css';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/watchlist"
          element={
            <ProtectedRoute>
              <WatchlistPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/watchlist" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
