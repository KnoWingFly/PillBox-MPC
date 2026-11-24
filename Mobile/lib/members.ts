// Caregivers of an elderly profile and invitations by code (FastAPI backend, /api/v1).
// Roles live on the elderly profile, not on a pillbox (Backend/app/services/access.py):
// OWNER manages everything, ADMIN manages schedules and invites monitors, PEMANTAU only watches.
// See docs/ROLES_FEATURE_PLAN.md.
import { AppConfig } from '@/config';

import { backendRequest as backend } from './api';
import type { PillboxRole } from './devices';
import { requireBackend } from './elderly';

/** Roles a caregiver can be given by invitation or by a role change (never OWNER). */
export type GrantableRole = Exclude<PillboxRole, 'OWNER'>;

/** GET /elderly/{id}/caregivers item (CaregiverOut). */
export type Member = {
  caregiver_id: string;
  full_name: string;
  role: PillboxRole;
  relationship_label: string | null;
  added_at: string;
};

/** GET /elderly/{id}/invitations item (InvitationOut). The code itself is never listed. */
export type PendingInvitation = {
  invitation_id: string;
  role: PillboxRole;
  relationship_label: string | null;
  invited_by_user_id: string | null;
  invited_by_name: string | null;
  created_at: string;
  expires_at: string;
};

/** OWNER revokes any pending invitation, an ADMIN only their own (Backend services/invitations.py). */
export function canRevoke(myRole: PillboxRole | null, userId: string | null, invitation: PendingInvitation): boolean {
  return myRole === 'OWNER' || (myRole === 'ADMIN' && invitation.invited_by_user_id === userId);
}

/** POST /elderly/{id}/invitations 201 (InvitationCreated). `code` is returned only here. */
export type CreatedInvitation = {
  invitation_id: string;
  code: string;
  role: PillboxRole;
  relationship_label: string | null;
  expires_at: string;
};

/** POST /invitations/preview 200 (InvitationPreview). */
export type InvitationPreview = {
  elderly_name: string;
  invited_by_name: string | null;
  role: PillboxRole;
  relationship_label: string | null;
  expires_at: string;
};

/** POST /invitations/accept 200 (InvitationAccepted). */
export type AcceptedInvitation = { elderly_id: string; my_role: PillboxRole };

type Page<T> = { data: T[]; page: number; limit: number; total: number };

/** Roles each role may hand out (Backend GRANTABLE_ROLES, app/services/access.py). */
export function grantableRoles(giver: PillboxRole | null): GrantableRole[] {
  if (giver === 'OWNER') return ['ADMIN', 'PEMANTAU'];
  if (giver === 'ADMIN') return ['PEMANTAU'];
  return [];
}

export const canInvite = (role: PillboxRole | null): boolean => grantableRoles(role).length > 0;
export const canManageMembers = (role: PillboxRole | null): boolean => role === 'OWNER';

/** One page is enough: a profile has at most AppConfig.maxCaregiversPerElderly caregivers. */
const MEMBER_PAGE_LIMIT = Math.min(AppConfig.backendPageLimit, AppConfig.maxCaregiversPerElderly * 2);

export async function listMembers(elderlyId: string): Promise<Member[]> {
  requireBackend();
  const page = await backend<Page<Member>>(`/elderly/${elderlyId}/caregivers?limit=${MEMBER_PAGE_LIMIT}`);
  return page.data;
}

export async function listPendingInvitations(elderlyId: string): Promise<PendingInvitation[]> {
  requireBackend();
  const page = await backend<Page<PendingInvitation>>(
    `/elderly/${elderlyId}/invitations?limit=${AppConfig.backendPageLimit}`,
  );
  return page.data;
}

export async function createInvitation(
  elderlyId: string,
  role: GrantableRole,
  relationshipLabel: string | null,
): Promise<CreatedInvitation> {
  requireBackend();
  return backend<CreatedInvitation>(`/elderly/${elderlyId}/invitations`, 'POST', {
    role,
    ...(relationshipLabel ? { relationship_label: relationshipLabel } : {}),
  });
}

export async function revokeInvitation(elderlyId: string, invitationId: string): Promise<void> {
  requireBackend();
  await backend(`/elderly/${elderlyId}/invitations/${invitationId}`, 'DELETE');
}

export async function changeMemberRole(elderlyId: string, caregiverId: string, role: GrantableRole): Promise<Member> {
  requireBackend();
  return backend<Member>(`/elderly/${elderlyId}/caregivers/${caregiverId}`, 'PUT', { role });
}

/** Removes another caregiver (OWNER) or leaves the profile (caregiverId = the caller's own id). */
export async function removeMember(elderlyId: string, caregiverId: string): Promise<void> {
  requireBackend();
  await backend(`/elderly/${elderlyId}/caregivers/${caregiverId}`, 'DELETE');
}

export async function transferOwnership(elderlyId: string, newOwnerId: string): Promise<void> {
  requireBackend();
  await backend(`/elderly/${elderlyId}/transfer-ownership`, 'POST', { new_owner_caregiver_id: newOwnerId });
}

export async function previewInvitation(code: string): Promise<InvitationPreview> {
  requireBackend();
  return backend<InvitationPreview>('/invitations/preview', 'POST', { code });
}

export async function acceptInvitation(code: string): Promise<AcceptedInvitation> {
  requireBackend();
  return backend<AcceptedInvitation>('/invitations/accept', 'POST', { code });
}

const CODE_HALF = AppConfig.invitationCodeLength / 2;
/** A shared code inside other text, e.g. the WhatsApp message "... Kode undangan: K7QF-2M9X ...". */
const CODE_IN_TEXT = new RegExp(
  `[${AppConfig.invitationCodeAlphabet}]{${CODE_HALF}}-[${AppConfig.invitationCodeAlphabet}]{${CODE_HALF}}`,
);

/**
 * What the code field keeps: letters and digits only, uppercase, at most one code long. A paste
 * that contains a whole XXXX-XXXX code (with words around it) keeps just that code.
 */
export function cleanCodeInput(raw: string): string {
  const upper = raw.toUpperCase();
  const found = CODE_IN_TEXT.exec(upper)?.[0];
  return (found ?? upper).replace(/[^0-9A-Z]/g, '').slice(0, AppConfig.invitationCodeLength);
}

/** "ABCD1234" -> "ABCD-1234" for display. */
export function formatCode(clean: string): string {
  return clean.length > CODE_HALF ? `${clean.slice(0, CODE_HALF)}-${clean.slice(CODE_HALF)}` : clean;
}
