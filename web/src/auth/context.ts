import { createContext } from 'react';
import type { AuthStatus, AuthUser } from '../types/auth';

export interface LoginInput {
  email: string;
  password: string;
}

export interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  login: (input: LoginInput) => Promise<void>;
  mockLogin: () => Promise<void>;
  logout: () => Promise<void>;
  getIdToken: () => Promise<string | null>;
  canUseFirebaseAuth: boolean;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
