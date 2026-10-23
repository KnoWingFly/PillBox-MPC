import { useState } from 'react';
import { Text, TextInput, TouchableOpacity, View, type TextInputProps } from 'react-native';

import { Strings } from '@/constants/strings';

type Props = TextInputProps & { label: string; secureToggle?: boolean };

// Labeled input; with `secureToggle` it becomes a password field with show/hide.
export default function FormField({ label, secureToggle, ...inputProps }: Props) {
  const [hidden, setHidden] = useState(true);

  return (
    <View className="mb-4">
      <Text className="text-sm font-medium text-gray-700 mb-1 ml-1">{label}</Text>
      <View className="flex-row items-center bg-gray-50 border border-gray-200 rounded-xl">
        <TextInput
          className="flex-1 px-4 py-3.5 text-gray-900"
          placeholderTextColor="#9ca3af"
          secureTextEntry={secureToggle ? hidden : inputProps.secureTextEntry}
          autoCorrect={false}
          {...inputProps}
        />
        {secureToggle && (
          <TouchableOpacity
            onPress={() => setHidden((h) => !h)}
            className="px-4 py-3"
            accessibilityRole="button"
            accessibilityLabel={hidden ? Strings.auth.showPassword : Strings.auth.hidePassword}>
            <Text className="text-sm font-medium text-blue-600">
              {hidden ? Strings.auth.showPassword : Strings.auth.hidePassword}
            </Text>
          </TouchableOpacity>
        )}
      </View>
    </View>
  );
}
