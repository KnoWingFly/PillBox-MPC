import { Text } from 'react-native';

/**
 * "… Ketentuan Layanan dan Kebijakan Privasi …" with the two document names emphasized.
 * Not links yet: the app has no terms or privacy URLs to open.
 */
export default function LegalLine({ parts, centered = false }: {
  parts: { prefix: string; terms: string; join: string; privacy: string; suffix: string };
  centered?: boolean;
}) {
  return (
    <Text className={`text-caption text-ink-muted ${centered ? 'text-center' : ''}`}>
      {parts.prefix}
      <Text className="font-bold text-primary">{parts.terms}</Text>
      {parts.join}
      <Text className="font-bold text-primary">{parts.privacy}</Text>
      {parts.suffix}
    </Text>
  );
}
