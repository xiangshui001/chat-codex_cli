import { describe, expect, it, vi } from 'vitest';
import { HttpClient } from './http';
import { ClientError } from './client';

const request = {
  request_id: 'same-request',
  repository: 'local/smoke',
  intent: { action: 'pause' as const },
};

describe('HTTP Harness transport', () => {
  it('sends the original request once and queries the same identity', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(
      async () =>
        new Response('{"outcome":"unknown"}', {
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    const client = new HttpClient('/api/v2', fetcher);
    await client.pauseQueue(request);
    await client.getControlReceipt(request.request_id);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0][0]).toBe('/api/v2/controls');
    expect(fetcher.mock.calls[0][1]?.body).toBe(JSON.stringify(request));
    expect(fetcher.mock.calls[1][0]).toBe('/api/v2/controls/same-request');
    expect(fetcher.mock.calls[1][1]?.method).toBe('GET');
  });

  it('connection failure does not silently retry or use mock', async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline'));
    const client = new HttpClient('/api/v2', fetcher);
    await expect(client.pauseQueue(request)).rejects.toMatchObject({ code: 'unavailable' });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('maps forbidden to a client authorization error', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockImplementation(async () => new Response('{}', { status: 403 }));
    await expect(new HttpClient('/api/v2', fetcher).getSession()).rejects.toBeInstanceOf(
      ClientError,
    );
    await expect(new HttpClient('/api/v2', fetcher).getSession()).rejects.toMatchObject({
      code: 'forbidden',
    });
  });

  it('invalid JSON is unavailable, never a successful state', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('<html>error</html>'));
    await expect(new HttpClient('/api/v2', fetcher).getRuntimeStatus()).rejects.toMatchObject({
      code: 'unavailable',
    });
  });
});
