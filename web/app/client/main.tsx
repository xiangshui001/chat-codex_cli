import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createMockClient } from '../api-client/mock';
import { HttpClient } from '../api-client/http';
import { AppShell } from './AppShell';
import { LoginPage } from './LoginPage';
import { LiveWorkbench } from './LiveWorkbench';

// Explicit transport selection. A live failure never switches to mock.
const localHarness = new URLSearchParams(window.location.search).get('harness') === 'local-smoke';
const { client, demo } = localHarness
  ? { client: new HttpClient(), demo: undefined }
  : createMockClient();
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
      localHarness={localHarness}
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
    {new URLSearchParams(window.location.search).get('view') === 'live' ? (
      <LiveWorkbench />
    ) : (
      <PreviewEntry />
    )}
  </StrictMode>,
);
