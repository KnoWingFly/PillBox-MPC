import { useState } from 'react';
import { View, TextInput, Text, Alert, TouchableOpacity, KeyboardAvoidingView, Platform, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { supabase } from '@root/utils/supabase';
import GoogleSignInButton from '@root/components/auth/google-sign-in-button';

export default function LoginScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [mode, setMode] = useState<'signIn' | 'signUp'>('signIn');
  const [loading, setLoading] = useState(false);

  async function onSubmit() {
    if (mode === 'signUp' && password !== confirmPassword) {
      Alert.alert('Error', 'Passwords do not match.');
      return;
    }

    setLoading(true);
    let error;

    if (mode === 'signIn') {
      const result = await supabase.auth.signInWithPassword({ email, password });
      error = result.error;
    } else {
      const result = await supabase.auth.signUp({ email, password });
      error = result.error;
    }

    setLoading(false);
    
    if (error) {
      Alert.alert('Error', error.message);
    } else if (mode === 'signUp') {
      Alert.alert('Success', 'Please check your email to verify your account.', [
        { text: 'OK', onPress: () => setMode('signIn') }
      ]);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-white">
      <KeyboardAvoidingView 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        className="flex-1 justify-center px-6"
      >
        <View className="mb-10 items-center">
          <View className="h-16 w-16 bg-blue-500 rounded-2xl items-center justify-center mb-4 shadow-sm shadow-blue-500/50">
            <Text className="text-white text-3xl font-bold">P</Text>
          </View>
          <Text className="text-3xl font-bold text-gray-900 mb-2">
            Welcome to PillCare
          </Text>
          <Text className="text-gray-500 text-center">
            {mode === 'signIn' ? 'Sign in to access your caregiver dashboard' : 'Create an account to get started'}
          </Text>
        </View>

        <View className="space-y-4">
          <View>
            <Text className="text-sm font-medium text-gray-700 mb-1 ml-1">Email</Text>
            <TextInput
              className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3.5 text-gray-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              placeholder="Enter your email"
              placeholderTextColor="#9ca3af"
              autoCapitalize="none"
              keyboardType="email-address"
              value={email}
              onChangeText={setEmail}
              editable={!loading}
            />
          </View>

          <View>
            <Text className="text-sm font-medium text-gray-700 mb-1 ml-1">Password</Text>
            <TextInput
              className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3.5 text-gray-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              placeholder="Enter your password"
              placeholderTextColor="#9ca3af"
              secureTextEntry
              value={password}
              onChangeText={setPassword}
              editable={!loading}
            />
          </View>

          {mode === 'signUp' && (
            <View>
              <Text className="text-sm font-medium text-gray-700 mb-1 ml-1">Confirm Password</Text>
              <TextInput
                className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3.5 text-gray-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                placeholder="Confirm your password"
                placeholderTextColor="#9ca3af"
                secureTextEntry
                value={confirmPassword}
                onChangeText={setConfirmPassword}
                editable={!loading}
              />
            </View>
          )}

          {mode === 'signIn' && (
            <TouchableOpacity className="self-end mt-1">
              <Text className="text-sm font-medium text-blue-600">Forgot password?</Text>
            </TouchableOpacity>
          )}

          <TouchableOpacity 
            onPress={onSubmit}
            disabled={loading}
            className={`w-full bg-blue-600 rounded-xl py-4 items-center justify-center mt-2 shadow-sm shadow-blue-600/30 ${loading ? 'opacity-70' : 'opacity-100'}`}
          >
            {loading ? (
              <ActivityIndicator color="white" />
            ) : (
              <Text className="text-white font-semibold text-lg">
                {mode === 'signIn' ? 'Sign In' : 'Create Account'}
              </Text>
            )}
          </TouchableOpacity>
        </View>

        <View className="flex-row items-center my-6">
          <View className="flex-1 h-[1px] bg-gray-200" />
          <Text className="mx-4 text-gray-500 font-medium">OR</Text>
          <View className="flex-1 h-[1px] bg-gray-200" />
        </View>

        <GoogleSignInButton />

        <View className="mt-8 flex-row justify-center">
          <Text className="text-gray-600">
            {mode === 'signIn' ? "Don't have an account? " : 'Already have an account? '}
          </Text>
          <TouchableOpacity onPress={() => {
            setMode(mode === 'signIn' ? 'signUp' : 'signIn');
            setConfirmPassword('');
          }}>
            <Text className="font-semibold text-blue-600">
              {mode === 'signIn' ? 'Sign up' : 'Sign in'}
            </Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}