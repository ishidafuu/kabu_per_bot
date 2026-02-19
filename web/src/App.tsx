import { Suspense, lazy } from 'react';
import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom';
import { ProtectedRoute } from './components/ProtectedRoute';
import './styles/app.css';

const LoginPage = lazy(async () => ({ default: (await import('./pages/LoginPage')).LoginPage }));
const DashboardPage = lazy(async () => ({ default: (await import('./pages/DashboardPage')).DashboardPage }));
const WatchlistPage = lazy(async () => ({ default: (await import('./pages/WatchlistPage')).WatchlistPage }));
const WatchlistHistoryPage = lazy(async () => ({
  default: (await import('./pages/WatchlistHistoryPage')).WatchlistHistoryPage,
}));
const NotificationLogsPage = lazy(async () => ({
  default: (await import('./pages/NotificationLogsPage')).NotificationLogsPage,
}));
const UserGuidePage = lazy(async () => ({ default: (await import('./pages/UserGuidePage')).UserGuidePage }));
const OpsPage = lazy(async () => ({ default: (await import('./pages/OpsPage')).OpsPage }));

const routeFallback = <div className="route-loading">読み込み中...</div>;

function App() {
  return (
    <Router>
      <Routes>
        <Route
          path="/login"
          element={
            <Suspense fallback={routeFallback}>
              <LoginPage />
            </Suspense>
          }
        />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <Suspense fallback={routeFallback}>
                <DashboardPage />
              </Suspense>
            </ProtectedRoute>
          }
        />
        <Route
          path="/watchlist"
          element={
            <ProtectedRoute>
              <Suspense fallback={routeFallback}>
                <WatchlistPage />
              </Suspense>
            </ProtectedRoute>
          }
        />
        <Route
          path="/watchlist/history"
          element={
            <ProtectedRoute>
              <Suspense fallback={routeFallback}>
                <WatchlistHistoryPage />
              </Suspense>
            </ProtectedRoute>
          }
        />
        <Route
          path="/notifications/logs"
          element={
            <ProtectedRoute>
              <Suspense fallback={routeFallback}>
                <NotificationLogsPage />
              </Suspense>
            </ProtectedRoute>
          }
        />
        <Route
          path="/guide"
          element={
            <ProtectedRoute>
              <Suspense fallback={routeFallback}>
                <UserGuidePage />
              </Suspense>
            </ProtectedRoute>
          }
        />
        <Route
          path="/ops"
          element={
            <ProtectedRoute>
              <Suspense fallback={routeFallback}>
                <OpsPage />
              </Suspense>
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
