import { Pressable, Text } from 'react-native';

/** "Sudah punya akun? Masuk ke Akun": a short question followed by a tappable link. */
export function LinkPrompt({ question, link, onPress }: { question: string; link: string; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="link"
      accessibilityLabel={`${question} ${link}`}
      onPress={onPress}
      className="min-h-[44px] items-center justify-center active:opacity-75">
      <Text className="text-center text-body-sm text-ink-muted">
        {`${question} `}
        <Text className="font-bold text-primary underline">{link}</Text>
      </Text>
    </Pressable>
  );
}
