// Indonesian phone number helpers shared by the sign-up and elderly profile forms.
import { AppConfig } from '@/config';

const PHONE_SEPARATORS = /[\s\-().]/g;

/** "0812-3456-7890", "62812…", "+62812…" -> "+62812…"; null when it is not a valid Indonesian number. */
export function normalizeIdPhone(input: string): string | null {
  const code = AppConfig.phoneCountryCode;
  let digits = input.replace(PHONE_SEPARATORS, '');
  if (digits.startsWith(`+${code}`)) digits = digits.slice(code.length + 1);
  else if (digits.startsWith(code)) digits = digits.slice(code.length);
  else if (digits.startsWith('0')) digits = digits.slice(1);
  else return null;
  const { phoneNationalMinDigits: min, phoneNationalMaxDigits: max } = AppConfig;
  if (!/^[1-9]\d*$/.test(digits) || digits.length < min || digits.length > max) return null;
  return `+${code}${digits}`;
}

/** Same as normalizeIdPhone, for an input that shows the "+62" prefix outside the box (national part only). */
export function normalizeIdNationalPhone(national: string): string | null {
  const trimmed = national.replace(PHONE_SEPARATORS, '');
  return normalizeIdPhone(trimmed.startsWith('0') ? trimmed : `0${trimmed}`);
}
