import { useState } from 'react';
import { Text, View } from 'react-native';

import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';
import { errorMessage } from '@/lib/api/error-message';
import {
  acceptInvitation,
  cleanCodeInput,
  formatCode,
  previewInvitation,
  type AcceptedInvitation,
  type InvitationPreview,
} from '@root/lib/members';

import { TextField } from '../form/text-field';
import { Avatar } from '../pillbox/blocks';
import { Dialog, DialogHeader } from '../pillbox/dialog';
import { Button } from '../pillbox/ui';
import { RoleBadge } from './role-badge';

const S = Strings.members;

type JoinProps = {
  visible: boolean;
  onJoined: (result: AcceptedInvitation, elderlyName: string) => void;
  onClose: () => void;
};

/**
 * "Punya kode undangan?": enter the code, see who invites you and as what, then join.
 * Nothing changes until "Gabung" (the backend adds the role only on accept). The body mounts on
 * every opening, so the field always starts empty.
 */
export function JoinCodeDialog(props: JoinProps) {
  const [busy, setBusy] = useState(false);
  return (
    <Dialog visible={props.visible} busy={busy} onCancel={props.onClose}>
      {props.visible && <JoinBody {...props} busy={busy} setBusy={setBusy} />}
    </Dialog>
  );
}

function JoinBody({ onJoined, onClose, busy, setBusy }: JoinProps & { busy: boolean; setBusy: (busy: boolean) => void }) {
  const [code, setCode] = useState('');
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const complete = code.length === AppConfig.invitationCodeLength;

  const run = async (step: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await step();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const lookUp = () =>
    run(async () => {
      setPreview(await previewInvitation(code));
    });

  const join = () =>
    run(async () => {
      if (!preview) return;
      const result = await acceptInvitation(code);
      onJoined(result, preview.elderly_name);
    });

  if (!preview) {
    return (
      <View className="gap-4">
        <DialogHeader icon="key-outline" tone="primary" title={S.joinTitle} />
        <TextField
          label={S.joinTitle}
          hint={S.joinHint}
          error={error}
          value={formatCode(code)}
          onChangeText={(text) => setCode(cleanCodeInput(text))}
          autoCapitalize="characters"
          autoComplete="off"
          returnKeyType="next"
          onSubmitEditing={() => {
            if (complete) void lookUp();
          }}
          editable={!busy}
        />
        <Button label={S.joinNext} onPress={() => void lookUp()} loading={busy} disabled={!complete} />
        <Button label={Strings.common.close} variant="ghost" onPress={onClose} disabled={busy} />
      </View>
    );
  }

  return (
    <View className="gap-4">
      <View className="items-center gap-2 pt-2">
        <Avatar name={preview.elderly_name} size="lg" />
        <Text className="text-heading font-bold text-ink" accessibilityRole="header">
          {preview.elderly_name}
        </Text>
        <Text className="text-center text-body text-ink-muted">
          {preview.invited_by_name ? S.joinInvitedBy(preview.invited_by_name) : S.joinInvited}
        </Text>
        <RoleBadge role={preview.role} />
      </View>
      {error ? <Text className="text-body-sm text-missed-fg">{error}</Text> : null}
      <View className="flex-row gap-2">
        <View className="flex-1">
          <Button label={S.decline} variant="secondary" onPress={onClose} disabled={busy} />
        </View>
        <View className="flex-1">
          <Button label={S.join} onPress={() => void join()} loading={busy} />
        </View>
      </View>
    </View>
  );
}
