import { useEffect, useRef, useState } from 'react';
import { Building2, Sparkles } from 'lucide-react';
import type { LibraryInstance } from '../public/tisu/astral-library/index';

type LibraryModule = Pick<typeof import('../public/tisu/astral-library/index'), 'mountLibrary'>;

/** The TISU scene stays outside workspace state and is only a decorative still view. */
export function LibraryModel() {
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'fallback'>('loading');
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 900px)').matches);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 900px)');
    const changed = () => setCompact(media.matches);
    media.addEventListener('change', changed);
    return () => media.removeEventListener('change', changed);
  }, []);

  useEffect(() => {
    const container = host.current!;
    let cancelled = false;
    let library: LibraryInstance | null = null;
    let observer: ResizeObserver | null = null;
    let canvas: HTMLCanvasElement | null = null;
    const paint = () => {
      if (cancelled || document.hidden || !container.clientWidth || !container.clientHeight) return;
      // TISU resize updates the viewport; render one frame and immediately cancel RAF.
      library?.resume();
      library?.pause();
    };
    const release = () => {
      observer?.disconnect();
      document.removeEventListener('visibilitychange', paint);
      canvas?.removeEventListener('webglcontextlost', fail);
      library?.dispose();
      library = null;
      canvas = null;
    };
    const fail = () => {
      release();
      if (!cancelled) {
        container.replaceChildren();
        setStatus('fallback');
      }
    };
    setStatus('loading');
    async function mount() {
      try {
        const url = new URL(
          `${import.meta.env.BASE_URL}tisu/astral-library/library.js`,
          document.baseURI,
        ).href;
        const module = (await import(/* @vite-ignore */ url)) as LibraryModule;
        if (cancelled) return; // Includes StrictMode cleanup and leaving during lazy import.
        library = module.mountLibrary(container, {
          keyboard: 'off',
          maxPixelRatio: compact ? 1 : 1.25,
          shadows: !compact,
        });
        library.pause();
        canvas = container.querySelector('canvas');
        if (canvas) {
          canvas.tabIndex = -1;
          canvas.style.touchAction = 'auto';
          canvas.addEventListener('webglcontextlost', fail);
        }
        observer = new ResizeObserver(paint);
        observer.observe(container);
        document.addEventListener('visibilitychange', paint);
        setStatus('ready');
      } catch {
        fail();
      }
    }
    void mount();
    return () => {
      cancelled = true;
      release();
    };
  }, [compact]);

  return (
    <figure className="library-model" data-testid="library-model" data-status={status}>
      <div className="library-scene" ref={host} aria-hidden="true" />
      {status !== 'ready' && (
        <div className="library-placeholder" aria-hidden="true">
          <Building2 size={48} />
          <div className="placeholder-orbit" />
        </div>
      )}
      <figcaption className="library-caption">
        <Sparkles size={15} />
        <div>
          <strong>星穹图书馆</strong>
          <span>
            {status === 'loading'
              ? '正在准备外景模型…'
              : status === 'fallback'
                ? '模型暂不可用，你仍可进入工作区'
                : '静态外景 · 任务之外的一片宁静'}
          </span>
        </div>
        <span className="library-caption-mark">TISU</span>
      </figcaption>
    </figure>
  );
}
