import { Text, View } from 'react-native';

import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';
import { PASSWORD_STRENGTH_STEPS, passwordStrength } from '@/lib/password-strength';

const S = Strings.signUp;

// Bar color per score (index = score). Written out in full so Tailwind can find the classes.
const FILLED = ['bg-line', 'bg-missed-solid', 'bg-late-solid', 'bg-ontime-solid', 'bg-ontime-solid'];

/** Four bars under the password field, the strength label and the rule. */
export default function PasswordStrengthMeter({ password }: { password: string }) {
  const score = passwordStrength(password);
  const level = S.strengthLevels[score];
  return (
    <View className="gap-1.5" accessible accessibilityLabel={S.strengthLabel(level)} accessibilityLiveRegion="polite">
      <View className="flex-row gap-1.5">
        {Array.from({ length: PASSWORD_STRENGTH_STEPS }, (_, i) => (
          <View key={i} className={`h-1.5 flex-1 rounded-full ${i < score ? FILLED[score] : 'bg-line'}`} />
        ))}
      </View>
      <View className="flex-row justify-between gap-2">
        <Text className="text-caption text-ink-muted">{S.strengthLabel(level)}</Text>
        <Text className="text-caption text-ink-muted">{S.passwordRule(AppConfig.passwordMinLength)}</Text>
      </View>
    </View>
  );
}
