export type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

export interface AuthUser {
  uid: string;
  email: string;
  provider: 'firebase' | 'mock';
}
