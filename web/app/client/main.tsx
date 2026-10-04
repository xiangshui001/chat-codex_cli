import { StrictMode, Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import { LiveWorkbench } from './LiveWorkbench';

const params = new URLSearchParams(window.location.search);
const preview = params.get('view') === 'demo' || params.get('harness') === 'local-smoke';
const DemoEntry = lazy(() => import('./DemoEntry'));
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {preview ? (
      <Suspense fallback={<p>正在加载演示环境…</p>}>
        <DemoEntry />
      </Suspense>
    ) : (
      <LiveWorkbench />
    )}
  </StrictMode>,
);
