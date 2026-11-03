import { Text, View } from 'react-native';

/** Horizontal rule with a short label in the middle, e.g. "atau masuk dengan". */
export function DividerLabel({ label }: { label: string }) {
  return (
    <View className="flex-row items-center gap-3">
      <View className="h-px flex-1 bg-line" />
      <Text className="text-caption text-ink-muted">{label}</Text>
      <View className="h-px flex-1 bg-line" />
    </View>
  );
}
