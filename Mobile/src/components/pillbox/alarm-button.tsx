import { Strings } from '@/constants/strings';

import { Button, type ButtonVariant, type IconName } from './ui';

/** The pillbox alarm a caregiver started ("Bunyikan Alarm", "Tes Pengingat"): while it rings, it can be stopped. */
export interface AlarmControl {
  ringing: boolean;
  stopping: boolean;
  onStop: () => void;
}

/** Starts an alarm on the pillbox; while that alarm rings, the same spot becomes "Hentikan Alarm". */
export function AlarmButton({
  label,
  icon,
  variant,
  size,
  starting,
  onStart,
  alarm,
}: {
  label: string;
  icon: IconName;
  variant: ButtonVariant;
  size?: 'sm' | 'md';
  starting: boolean;
  onStart: () => void;
  alarm: AlarmControl;
}) {
  if (alarm.ringing) {
    return (
      <Button
        label={Strings.alarm.stop}
        icon="stop-circle-outline"
        variant="danger"
        size={size}
        loading={alarm.stopping}
        onPress={alarm.onStop}
      />
    );
  }
  return <Button label={label} icon={icon} variant={variant} size={size} loading={starting} onPress={onStart} />;
}
