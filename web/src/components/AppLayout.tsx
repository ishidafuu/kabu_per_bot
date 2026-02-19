import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

interface AppLayoutProps {
  title: string;
  children: ReactNode;
  subtitle?: string;
}

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

const PRIMARY_NAV_ITEMS: NavItem[] = [
  { to: '/dashboard', label: 'ダッシュボード' },
  { to: '/guide', label: '使い方ガイド' },
  { to: '/watchlist', label: 'ウォッチリスト', end: true },
  { to: '/watchlist/history', label: '履歴' },
  { to: '/notifications/logs', label: '通知ログ' },
  { to: '/ops', label: '運用操作' },
];

export const AppLayout = ({ title, subtitle, children }: AppLayoutProps): ReactNode => {
  const { user, logout } = useAuth();

  return (
    <main className="page-shell">
      <header className="top-bar panel">
        <div>
          <h1>{title}</h1>
          <p className="muted">{subtitle ?? `ログイン中: ${user?.email ?? 'unknown'}`}</p>
        </div>
        <div className="top-actions">
          <button type="button" className="ghost" onClick={() => void logout()}>
            ログアウト
          </button>
        </div>
      </header>

      <nav className="panel page-nav" aria-label="主要メニュー">
        {PRIMARY_NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      {children}
    </main>
  );
};
