import type { ComponentType } from 'react';
import { Home, TrendingUp, Briefcase, Trophy, Zap, LogOut, HelpCircle } from 'lucide-react';
import { useAuth } from '../lib/auth';
import { toNumber } from '../lib/types';

type Page = 'dashboard' | 'markets' | 'portfolio' | 'leaderboards' | 'tournaments' | 'player';

interface NavItem {
  id: Page;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Home', icon: Home },
  { id: 'markets', label: 'Market', icon: TrendingUp },
  { id: 'portfolio', label: 'My Team', icon: Briefcase },
  { id: 'leaderboards', label: 'Rankings', icon: Trophy },
  { id: 'tournaments', label: 'Events', icon: Zap },
];

interface SidebarProps {
  currentPage: Page;
  navigate: (page: Page) => void;
  onShowIntro: () => void;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function Sidebar({ currentPage, navigate, onShowIntro }: SidebarProps) {
  const { user, wallet, logout } = useAuth();
  const activePage = currentPage === 'player' ? 'markets' : currentPage;
  const cash = wallet ? toNumber(wallet.cash_balance) : null;

  return (
    <aside
      className="w-[200px] shrink-0 h-screen flex flex-col border-r border-border"
      style={{ background: 'var(--sidebar)' }}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-border">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: 'linear-gradient(135deg, var(--primary), var(--accent))' }}
        >
          <span className="font-mono font-bold" style={{ fontSize: 14, color: '#020610' }}>F</span>
        </div>
        <div>
          <p className="font-bold tracking-wider" style={{ fontSize: 14, color: 'var(--foreground)' }}>FORECAST</p>
          <p className="text-muted-foreground" style={{ fontSize: 10 }}>Esports Markets</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map(item => {
          const active = activePage === item.id;
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => navigate(item.id)}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all text-left"
              style={{
                background: active ? 'rgba(0,200,255,0.1)' : 'transparent',
                color: active ? 'var(--primary)' : 'var(--muted-foreground)',
                fontWeight: active ? 600 : 400,
                fontSize: 14,
              }}
            >
              <Icon className="w-5 h-5 shrink-0" />
              <span className="flex-1">{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* How it works */}
      <div className="px-3 pb-1">
        <button
          onClick={onShowIntro}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all text-left hover:bg-white/5"
          style={{ color: 'var(--muted-foreground)', fontSize: 14 }}
        >
          <HelpCircle className="w-5 h-5 shrink-0" />
          <span className="flex-1">How it works</span>
        </button>
      </div>

      {/* Cash balance */}
      {cash !== null && (
        <div className="px-4 pb-2">
          <div className="rounded-xl border border-border p-3" style={{ background: 'rgba(0,0,0,0.3)' }}>
            <p className="text-muted-foreground" style={{ fontSize: 10 }}>Cash to Invest</p>
            <p className="font-mono font-bold mt-0.5" style={{ fontSize: 16, color: 'var(--foreground)' }}>
              ${cash.toLocaleString('en-US', { maximumFractionDigits: 0 })}
            </p>
          </div>
        </div>
      )}

      {/* User */}
      <div className="border-t border-border p-3">
        <button
          onClick={logout}
          title="Log out"
          className="w-full flex items-center gap-3 p-2.5 rounded-xl hover:bg-white/5 transition-colors"
        >
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 font-mono font-bold"
            style={{ fontSize: 12, background: 'linear-gradient(135deg, var(--accent), var(--primary))', color: '#fff' }}
          >
            {user ? initials(user.display_name) : '?'}
          </div>
          <div className="text-left min-w-0 flex-1">
            <p className="font-medium truncate" style={{ fontSize: 13, color: 'var(--foreground)' }}>
              {user?.display_name ?? 'Loading…'}
            </p>
            <p style={{ fontSize: 11, color: 'var(--muted-foreground)' }}>Log out</p>
          </div>
          <LogOut className="w-4 h-4 text-muted-foreground shrink-0" />
        </button>
      </div>
    </aside>
  );
}
