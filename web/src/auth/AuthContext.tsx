import {
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut,
} from 'firebase/auth';
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { appConfig } from '../lib/config';
import { firebaseAuth, isFirebaseConfigured } from '../lib/firebase';
import type { AuthStatus, AuthUser } from '../types/auth';
import { AuthContext, type LoginInput } from './context';

const MOCK_STORAGE_KEY = 'kabu_per_bot.mock_user';

const readMockUser = (): AuthUser | null => {
  const raw = localStorage.getItem(MOCK_STORAGE_KEY);

  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as AuthUser;
    if (!parsed.email || !parsed.uid) {
      return null;
    }

    return parsed;
  } catch {
    return null;
  }
};

export const AuthProvider = ({ children }: { children: ReactNode }): ReactNode => {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);

  const canUseFirebaseAuth = !appConfig.useMockAuth && isFirebaseConfigured && Boolean(firebaseAuth);

  useEffect(() => {
    if (!canUseFirebaseAuth || !firebaseAuth) {
      const mockUser = readMockUser();
      setUser(mockUser);
      setStatus(mockUser ? 'authenticated' : 'anonymous');
      return;
    }

    const unsubscribe = onAuthStateChanged(firebaseAuth, (firebaseUser) => {
      if (!firebaseUser) {
        setUser(null);
        setStatus('anonymous');
        return;
      }

      setUser({
        uid: firebaseUser.uid,
        email: firebaseUser.email ?? 'no-email',
        provider: 'firebase',
      });
      setStatus('authenticated');
    });

    return unsubscribe;
  }, [canUseFirebaseAuth]);

  const login = useCallback(
    async ({ email, password }: LoginInput): Promise<void> => {
      if (!canUseFirebaseAuth || !firebaseAuth) {
        throw new Error(
          'Firebase認証の設定が不足しています。.env.localに認証情報を設定するか、モック認証を利用してください。',
        );
      }

      await signInWithEmailAndPassword(firebaseAuth, email, password);
    },
    [canUseFirebaseAuth],
  );

  const mockLogin = useCallback(async (): Promise<void> => {
    const mockUser: AuthUser = {
      uid: 'mock-user',
      email: 'mock-user@example.com',
      provider: 'mock',
    };

    localStorage.setItem(MOCK_STORAGE_KEY, JSON.stringify(mockUser));
    setUser(mockUser);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    localStorage.removeItem(MOCK_STORAGE_KEY);

    if (canUseFirebaseAuth && firebaseAuth) {
      await signOut(firebaseAuth);
      return;
    }

    setUser(null);
    setStatus('anonymous');
  }, [canUseFirebaseAuth]);

  const getIdToken = useCallback(async (): Promise<string | null> => {
    if (canUseFirebaseAuth && firebaseAuth?.currentUser) {
      return firebaseAuth.currentUser.getIdToken();
    }

    if (readMockUser()) {
      return 'mock-token';
    }

    return null;
  }, [canUseFirebaseAuth]);

  const value = useMemo(
    () => ({
      status,
      user,
      login,
      mockLogin,
      logout,
      getIdToken,
      canUseFirebaseAuth,
    }),
    [status, user, login, mockLogin, logout, getIdToken, canUseFirebaseAuth],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
