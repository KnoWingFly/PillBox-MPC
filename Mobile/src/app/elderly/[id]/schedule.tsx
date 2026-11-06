import { useLocalSearchParams, useRouter } from 'expo-router';
import { ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Card, EmptyState } from '@/components/pillbox/ui';
import { BackHeader } from '@/components/ui/back-header';
import { Strings } from '@/constants/strings';

const S = Strings.elderlySchedule;

/**
 * Placeholder for the medication schedule page of a new elderly profile.
 * TODO: the real page loads GET /elderly/{id} and the profile's pillboxes; `id` is the elderly id.
 */
export default function ElderlyScheduleScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const toDashboard = () => router.dismissTo('/');

  return (
    <SafeAreaView className="flex-1 bg-canvas" edges={['top', 'left', 'right', 'bottom']}>
      <BackHeader title={S.title} onBack={toDashboard} />
      <ScrollView contentContainerClassName="gap-4 px-4 pb-8 pt-4" testID={`elderly-schedule-${id}`}>
        <Card>
          <EmptyState icon="calendar-outline" title={S.comingSoonTitle} text={S.comingSoonText} />
          <Button label={S.backToDashboard} variant="secondary" onPress={toDashboard} />
        </Card>
      </ScrollView>
    </SafeAreaView>
  );
}
