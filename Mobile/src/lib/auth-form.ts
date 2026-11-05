// Pure validation for the Masuk and Buat Akun forms. The auth server re-checks everything
// (src/server/schemas.ts); this only catches mistakes before the request.
import { Strings } from '@/constants/strings';
import type { RegisterInput } from '@/lib/api/auth';
import { newPasswordProblem } from '@/lib/password-strength';
import { normalizeIdNationalPhone } from '@/lib/phone';

const V = Strings.validation;

export type SignInValues = { email: string; password: string };

export type SignUpValues = {
  fullName: string;
  email: string;
  /** National part only; the "+62" prefix is shown outside the input. */
  phone: string;
  password: string;
  confirmPassword: string;
  consent: boolean;
};

export const EMPTY_SIGN_UP: SignUpValues = {
  fullName: '',
  email: '',
  phone: '',
  password: '',
  confirmPassword: '',
  consent: false,
};

export function validateSignIn(values: SignInValues): string | null {
  if (!values.email.trim() || !values.password) return V.required;
  return null;
}

export function validateSignUp(values: SignUpValues): string | null {
  if (!values.fullName.trim() || !values.email.trim() || !values.phone.trim() || !values.password) return V.required;
  if (!normalizeIdNationalPhone(values.phone)) return V.whatsappFormat;
  const passwordProblem = newPasswordProblem(values.password);
  if (passwordProblem) return passwordProblem;
  if (values.password !== values.confirmPassword) return V.passwordMismatch;
  if (!values.consent) return V.consentRequired;
  return null;
}

/** Request body (without timezone, which the auth context adds) for a form that passed validateSignUp. */
export function toRegisterInput(values: SignUpValues): Omit<RegisterInput, 'timezone'> {
  return {
    full_name: values.fullName.trim(),
    email: values.email.trim(),
    phone_number: normalizeIdNationalPhone(values.phone) ?? values.phone.trim(),
    password: values.password,
  };
}
