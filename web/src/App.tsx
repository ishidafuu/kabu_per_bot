import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom';
import { ProtectedRoute } from './components/ProtectedRoute';
import { LoginPage } from './pages/LoginPage';
import { NotificationLogsPage } from './pages/NotificationLogsPage';
import { WatchlistPage } from './pages/WatchlistPage';
import { WatchlistHistoryPage } from './pages/WatchlistHistoryPage';
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
        <Route
          path="/watchlist/history"
          element={
            <ProtectedRoute>
              <WatchlistHistoryPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/notifications/logs"
          element={
            <ProtectedRoute>
              <NotificationLogsPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/watchlist" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
