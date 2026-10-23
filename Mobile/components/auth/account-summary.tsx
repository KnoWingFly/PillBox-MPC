import { useEffect, useState } from 'react';
import { ActivityIndicator, Text, TouchableOpacity, View } from 'react-native';

import { Strings } from '@/constants/strings';
import { useAuth } from '@/hooks/use-auth';
import { errorMessage } from '@/lib/api/error-message';
import { settingApi, type Setting } from '@/lib/api/setting';

// Minimal proof that GET /api/setting works; the full Settings UI is out of scope.
export default function AccountSummary() {
  const { signOut } = useAuth();
  const [setting, setSetting] = useState<Setting | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    settingApi.get().then(setSetting, (err) => setError(errorMessage(err)));
  }, []);

  return (
    <View className="w-full rounded-2xl bg-gray-100 p-4 items-center">
      {setting ? (
        <>
          <Text className="text-xs text-gray-500">{Strings.auth.signedInAs}</Text>
          <Text className="text-lg font-semibold text-gray-900">{setting.full_name}</Text>
          <Text className="text-sm text-gray-600">{setting.email}</Text>
        </>
      ) : error ? (
        <Text className="text-sm text-red-600">{error}</Text>
      ) : (
        <ActivityIndicator />
      )}
      <TouchableOpacity
        onPress={async () => {
          setSigningOut(true);
          await signOut();
        }}
        disabled={signingOut}
        className={`mt-3 rounded-xl bg-blue-600 px-6 py-2.5 ${signingOut ? 'opacity-70' : ''}`}>
        <Text className="font-semibold text-white">{Strings.auth.signOut}</Text>
      </TouchableOpacity>
    </View>
  );
}
