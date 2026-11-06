import { createContext, useContext } from 'react';

/** Guest mode = the whole app, same look, but anything that needs an account asks the visitor to log in or sign up. */
export interface GuestState {
  isGuest: boolean;
  /** Pops up "Log in or create an account to use this feature". No-op for signed-in users. */
  requireAccount: (feature?: string) => void;
  /** Go to the login (or sign-up) screen. */
  goLogin: (mode?: 'login' | 'register') => void;
}

export const GuestContext = createContext<GuestState>({ isGuest: false, requireAccount: () => {}, goLogin: () => {} });
export const useGuest = () => useContext(GuestContext);
