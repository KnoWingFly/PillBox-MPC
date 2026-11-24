import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import * as tokens from '@/theme/tokens';
import type { PillboxRole } from '@root/lib/devices';

import { Dialog } from '../pillbox/dialog';
import { Button, Icon } from '../pillbox/ui';
import { ROLE_LOOK } from './role-badge';

const S = Strings.members;
const ROLES: PillboxRole[] = ['OWNER', 'ADMIN', 'PEMANTAU'];

/** "Apa bedanya?": a compact can / cannot grid instead of paragraphs. */
export function RoleInfoDialog({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  return (
    <Dialog visible={visible} onCancel={onClose}>
      <View className="gap-3">
        <Text className="text-heading font-bold text-ink" accessibilityRole="header">
          {S.infoTitle}
        </Text>
        <View className="flex-row items-end">
          <View className="flex-1" />
          {ROLES.map((role) => (
            <View key={role} className="w-[72px] items-center gap-1">
              <Icon name={ROLE_LOOK[role].icon} size={20} color={tokens.colors.primary.DEFAULT} />
              <Text className="text-caption font-semibold text-ink">{Strings.shell.roles[role]}</Text>
            </View>
          ))}
        </View>
        {S.infoRows.map((row) => (
          <View key={row.label} className="min-h-[44px] flex-row items-center border-t border-line">
            <Text className="flex-1 text-body-sm text-ink">{row.label}</Text>
            {ROLES.map((role) => (
              <View
                key={role}
                className="w-[72px] items-center"
                accessible
                accessibilityLabel={`${Strings.shell.roles[role]}: ${row[role] ? S.yes : S.no}`}>
                <Icon
                  name={row[role] ? 'checkmark-circle' : 'remove'}
                  size={22}
                  color={row[role] ? tokens.colors.ontime.fg : tokens.colors.ink.subtle}
                />
              </View>
            ))}
          </View>
        ))}
        <Text className="text-caption text-ink-muted">{S.infoFootnote}</Text>
        <Button label={Strings.common.close} variant="secondary" onPress={onClose} />
      </View>
    </Dialog>
  );
}
