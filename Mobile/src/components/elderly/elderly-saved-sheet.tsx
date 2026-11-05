import { Text, View } from 'react-native';

import { Strings } from '@/constants/strings';
import { ageFromBirthDate, validBirthDate, type ElderlyFormValues } from '@/lib/elderly-form';

import { Avatar } from '../pillbox/blocks';
import { Divider, InfoRow, StatusPill } from '../pillbox/ui';
import { SuccessSheet } from '../ui/success-sheet';

const S = Strings.elderlyForm;

/** "Profil Lansia Berhasil Disimpan!" after a complete save; pillboxes are paired afterwards. */
export function ElderlySavedSheet({
  values,
  phone,
  onSchedule,
  onHome,
}: {
  /** The saved form values; null = hidden. */
  values: ElderlyFormValues | null;
  /** The phone number as saved by the server (E.164); null when none was given. */
  phone: string | null;
  onSchedule: () => void;
  onHome: () => void;
}) {
  const birth = values ? validBirthDate(values.birthDate) : null;
  const age = birth ? S.ageYears(ageFromBirthDate(birth)) : null;
  const gender = values?.gender === 'FEMALE' ? S.genderFemale : values?.gender === 'MALE' ? S.genderMale : null;
  const name = values?.fullName.trim() || Strings.shell.elderlyFallback;

  return (
    <SuccessSheet
      visible={values !== null}
      title={S.savedTitle}
      message={S.savedText(name)}
      primary={{ label: S.setSchedule, icon: 'calendar-outline', onPress: onSchedule }}
      secondary={{ label: S.backHome, onPress: onHome }}
      onClose={onHome}>
      <View className="flex-row items-center gap-3">
        <Avatar name={name} />
        <View className="flex-1">
          <Text className="text-body font-bold text-ink" numberOfLines={1}>
            {name}
          </Text>
          {(age || gender) && <Text className="text-body-sm text-ink-muted">{S.savedMeta(age, gender)}</Text>}
        </View>
      </View>
      <Divider />
      <InfoRow icon="cube-outline" label={S.savedPillbox} value={S.savedPillboxNone} valueClassName="text-ink-muted" />
      {phone ? <InfoRow icon="call-outline" label={S.savedPhone} value={phone} /> : null}
      <View className="flex-row items-center justify-between">
        <Text className="text-body-sm text-ink-muted">{S.savedStatus}</Text>
        <StatusPill label={S.savedReady} tone="ontime" />
      </View>
    </SuccessSheet>
  );
}
