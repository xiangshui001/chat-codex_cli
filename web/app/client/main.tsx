import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createMockClient } from '../api-client/mock';
import { AppShell } from './AppShell';
import { LoginPage } from './LoginPage';

// The sole composition point. Replace with HttpClient only when a real API exists.
// There is deliberately no live-to-mock fallback.
const { client, demo } = createMockClient();
function PreviewEntry() {
  const isLogin = () => ['', '#', '#/', '#/login', '#login'].includes(window.location.hash);
  const [login, setLogin] = useState(isLogin);
  useEffect(() => {
    const changed = () => {
      setLogin(isLogin());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  // Preview routing only. Existing workspace deep links retain their behavior.
  return login ? (
    <LoginPage
      onEnter={() => {
        window.location.hash = '#/dashboard';
      }}
    />
  ) : (
    <AppShell client={client} demo={demo} />
  );
}
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PreviewEntry />
  </StrictMode>,
);
