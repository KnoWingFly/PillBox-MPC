import { useState } from 'react';
import { Linking, Pressable, Share, Text, View } from 'react-native';

import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';
import { errorMessage } from '@/lib/api/error-message';
import * as tokens from '@/theme/tokens';
import type { PillboxRole } from '@root/lib/devices';
import { createInvitation, grantableRoles, type CreatedInvitation, type GrantableRole } from '@root/lib/members';

import { Dialog, DialogHeader } from '../pillbox/dialog';
import { Button, Chip, Icon, IconBadge } from '../pillbox/ui';
import { ROLE_LOOK } from './role-badge';
import { daysLeft } from './time';

const S = Strings.members;

type InviteProps = {
  visible: boolean;
  elderlyId: string;
  elderlyName: string;
  myRole: PillboxRole | null;
  /** A pending invitation now exists: reload the list behind the dialog. */
  onCreated: () => void;
  onClose: () => void;
};

function RoleCard({ role, selected, onPress }: { role: GrantableRole; selected: boolean; onPress: () => void }) {
  const look = ROLE_LOOK[role];
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={`${Strings.shell.roles[role]}. ${S.roleShort[role]}`}
      onPress={onPress}
      className={`min-h-[64px] flex-row items-center gap-3 rounded-2xl border-2 p-3 active:opacity-75 ${
        selected ? 'border-primary bg-primary-light' : 'border-line bg-surface'
      }`}>
      <IconBadge icon={look.icon} tone={look.tone} />
      <View className="flex-1">
        <Text className="text-body font-bold text-ink">{Strings.shell.roles[role]}</Text>
        <Text className="text-body-sm text-ink-muted">{S.roleShort[role]}</Text>
      </View>
      {selected ? <Icon name="checkmark-circle" size={24} color={tokens.colors.primary.DEFAULT} /> : null}
    </Pressable>
  );
}

/**
 * Invite in two steps: choose access (+ optional relationship), then share the one-time code.
 * An ADMIN sees only "Pemantau" (Backend GRANTABLE_ROLES). The body mounts on every opening,
 * so each invitation starts from step 1.
 */
export function InviteDialog(props: InviteProps) {
  const [busy, setBusy] = useState(false);
  return (
    <Dialog visible={props.visible} busy={busy} onCancel={props.onClose}>
      {props.visible && <InviteBody {...props} busy={busy} setBusy={setBusy} />}
    </Dialog>
  );
}

function InviteBody({
  elderlyId,
  elderlyName,
  myRole,
  onCreated,
  onClose,
  busy,
  setBusy,
}: InviteProps & { busy: boolean; setBusy: (busy: boolean) => void }) {
  const roles = grantableRoles(myRole);
  // Preselect the least access.
  const [role, setRole] = useState<GrantableRole | null>(roles.includes('PEMANTAU') ? 'PEMANTAU' : (roles[0] ?? null));
  const [relationship, setRelationship] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedInvitation | null>(null);

  const create = async () => {
    if (!role || busy) return;
    setBusy(true);
    setError(null);
    try {
      setCreated(await createInvitation(elderlyId, role, relationship));
      onCreated();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!created) {
    return (
      <View className="gap-4">
        <DialogHeader icon="person-add-outline" tone="primary" title={S.inviteTitle} />
        <View className="gap-2" accessibilityRole="radiogroup" accessibilityLabel={S.inviteStepRole}>
          {roles.map((r) => (
            <RoleCard key={r} role={r} selected={role === r} onPress={() => setRole(r)} />
          ))}
        </View>
        <View className="gap-2">
          <Text className="text-body-sm font-semibold text-ink">{S.relationship}</Text>
          <View className="flex-row flex-wrap gap-2">
            {S.relationships.map((label) => (
              <Chip
                key={label}
                label={label}
                selected={relationship === label}
                onPress={() => setRelationship(relationship === label ? null : label)}
              />
            ))}
          </View>
        </View>
        {error ? <Text className="text-body-sm text-missed-fg">{error}</Text> : null}
        <Button label={S.createCode} icon="key-outline" onPress={() => void create()} loading={busy} disabled={!role} />
        <Button label={Strings.common.close} variant="ghost" onPress={onClose} disabled={busy} />
      </View>
    );
  }

  const days = daysLeft(created.expires_at);
  const message = S.shareMessage(elderlyName, created.code, days);
  const shareWhatsApp = () => {
    Linking.openURL(`${AppConfig.whatsappShareUrl}${encodeURIComponent(message)}`).catch(() => setError(S.shareFailed));
  };
  const shareOther = () => {
    Share.share({ message }).catch(() => setError(S.shareFailed));
  };

  return (
    <View className="gap-4">
      <DialogHeader icon="key-outline" tone="success" title={S.codeTitle} />
      <View className="items-center gap-1 rounded-2xl bg-canvas py-5">
        <Text selectable accessibilityLabel={S.codeA11y(created.code)} className="text-display font-bold tracking-widest text-ink">
          {created.code}
        </Text>
        <Text className="text-body-sm text-ink-muted">{S.codeValidity(days)}</Text>
      </View>
      <Text className="text-body-sm text-ink-muted">{S.codeHint}</Text>
      {error ? <Text className="text-body-sm text-missed-fg">{error}</Text> : null}
      <Button label={S.shareWhatsApp} icon="logo-whatsapp" variant="success" onPress={shareWhatsApp} />
      <Button label={S.shareOther} icon="share-outline" variant="secondary" onPress={shareOther} />
      <Button label={S.done} variant="ghost" onPress={onClose} />
    </View>
  );
}
