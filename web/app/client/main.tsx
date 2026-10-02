import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createMockClient } from '../api-client/mock';
import { AppShell } from './AppShell';

// The sole composition point. Replace with HttpClient only when a real API exists.
// There is deliberately no live-to-mock fallback.
const { client, demo } = createMockClient();
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppShell client={client} demo={demo} />
  </StrictMode>,
);
