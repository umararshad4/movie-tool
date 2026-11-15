import type { Answer, Result, Sources } from './app.contract.d.ts';

export const grants = 'net.fetch http://127.0.0.1:8787';

const SERVICE = 'http://127.0.0.1:8787';

async function post(path: string, body: unknown): Promise<Record<string, unknown>> {
  const response = await fetch(`${SERVICE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    exactTimeout: 120000,
  });
  const raw: unknown = await response.json().catch(() => ({}));
  const parsed = (raw ?? {}) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof parsed.error === 'string' && parsed.error
      ? parsed.error : `The service refused ${path} (HTTP ${response.status}).`);
  }
  return parsed;
}

function asString(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

function asOption(v: unknown) {
  const o = (v ?? {}) as Record<string, unknown>;
  return {
    id: asString(o.id),
    label: asString(o.label),
    filename: asString(o.filename),
    size: asString(o.size),
    quality: asString(o.quality),
    tier: typeof o.tier === 'number' ? o.tier : 0,
    state: typeof o.state === 'number' ? o.state : 2,
    url: asString(o.url),
    note: asString(o.note),
    error: asString(o.error),
  };
}

const sources: Sources = {
  resolve: async ([url]): Promise<Result<'resolve'>> => {
    const body = await post('/resolve', { url }).catch((e: unknown) => {
      throw new Error(e instanceof Error && e.message ? e.message : 'The resolve request failed.');
    });
    if (!Array.isArray(body.items)) {
      throw new Error('The service reply was invalid.');
    }
    return { items: body.items.map(asOption), error: asString(body.error) };
  },
  download: async ([url, id]): Promise<Result<'download'>> => {
    const body = await post('/download', { url, id }).catch((e: unknown) => {
      throw new Error(e instanceof Error && e.message ? e.message : 'The download request failed.');
    });
    if (body.job_id === undefined && body.error === undefined) {
      throw new Error('The service reply was invalid.');
    }
    return { ok: body.job_id !== undefined, error: asString(body.error) };
  },
  jobList: async (): Promise<Result<'jobList'>> => {
    const response = await fetch(`${SERVICE}/progress`, { exactTimeout: 5000 }).catch(() => null);
    if (!response || !response.ok) {
      // Unreachable service is data, not a refused reply: the view shows nothing.
      return { jobs: [], error: '' };
    }
    const body = (await response.json()) as Record<string, unknown>;
    if (!Array.isArray(body.jobs)) return { jobs: [], error: '' };
    const jobs = body.jobs.map((j) => {
      const o = (j ?? {}) as Record<string, unknown>;
      return {
        id: asString(o.id),
        label: asString(o.label),
        filename: asString(o.filename),
        state: asString(o.state),
        pct: typeof o.pct === 'number' ? Math.max(0, Math.min(100, Math.round(o.pct))) : 0,
        error: asString(o.error),
        path: asString(o.path),
      };
    });
    return { jobs, error: '' };
  },
};

export const answer: Answer = (source, args, store, storage, native) =>
  sources[source](args, store, storage, native);
