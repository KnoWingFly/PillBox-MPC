import { createContext, useContext, useEffect, useState, PropsWithChildren } from 'react';
import type { Session } from '@supabase/supabase-js';
import { supabase } from '@root/utils/supabase';

type AuthData = {
  session: Session | null;
  isLoading: boolean;
  isLoggedIn: boolean;
};

const AuthContext = createContext<AuthData>({
  session: null,
  isLoading: true,
  isLoggedIn: false,
});

export const useAuthContext = () => useContext(AuthContext);

export default function AuthProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setIsLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
    });

    return () => subscription.unsubscribe();
  }, []);

  return (
    <AuthContext.Provider value={{ session, isLoading, isLoggedIn: !!session }}>
      {children}
    </AuthContext.Provider>
  );
}