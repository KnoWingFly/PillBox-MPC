// Elderly profile service (FastAPI backend, /api/v1/elderly). The caller becomes OWNER.
import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';

import { BackendError, backendRequest as backend, USE_MOCK } from './api';
import type { PillboxRole } from './devices';

/** Profiles, members and invitations exist only on the backend, never in mock mode. */
export function requireBackend(): void {
  if (USE_MOCK) throw new BackendError(400, 'MOCK_UNSUPPORTED', Strings.apiErrors.MOCK_UNSUPPORTED);
}

/** GET /elderly item (ElderlyListItem), the fields the app uses. */
export type ElderlySummary = {
  id: string;
  full_name: string;
  nickname: string | null;
  my_role: PillboxRole;
  device_count: number;
};

/** The profiles the caller belongs to, with or without a pillbox. */
export async function listMyElderly(): Promise<ElderlySummary[]> {
  requireBackend();
  const page = await backend<{ data: ElderlySummary[] }>(`/elderly?limit=${AppConfig.backendPageLimit}`);
  return page.data;
}

export type Gender = 'FEMALE' | 'MALE';

/** POST /elderly body (ElderlyIn). Only full_name is required by the backend. */
export type ElderlyIn = {
  full_name: string;
  birth_date?: string | null; // YYYY-MM-DD
  gender?: Gender | null;
  contact_phone?: string | null; // E.164, e.g. +6281234567890
};

/** POST /elderly 201 response (ElderlyCreated). */
export type ElderlyCreated = {
  id: string;
  full_name: string;
  nickname: string | null;
  birth_date: string | null;
  gender: Gender | null;
  contact_phone: string | null;
  notes: string | null;
  device_count: number;
  my_role: PillboxRole;
  created_at: string;
};

export async function createElderly(body: ElderlyIn): Promise<ElderlyCreated> {
  requireBackend();
  return backend<ElderlyCreated>('/elderly', 'POST', body);
}

const BODY_PREFIX = 'body.';

/** 422 details keyed by body field, e.g. { full_name: '...' }. Empty for any other error. */
export function validationFields(err: unknown): Partial<Record<keyof ElderlyIn, string>> {
  if (!(err instanceof BackendError) || err.code !== 'VALIDATION_ERROR') return {};
  const fields: Partial<Record<keyof ElderlyIn, string>> = {};
  for (const d of err.details) {
    if (d.path.startsWith(BODY_PREFIX)) fields[d.path.slice(BODY_PREFIX.length) as keyof ElderlyIn] = d.message;
  }
  return fields;
}
