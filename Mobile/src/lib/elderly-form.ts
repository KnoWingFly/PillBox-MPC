// Pure helpers for the "Tambah Profil Lansia" form. Mirrors Backend/app/schemas/elderly.py ElderlyIn
// (name length, birth date range, E.164 phone) so most mistakes are caught before the request.
import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';
import type { ElderlyIn, Gender } from '@root/lib/elderly';

const E = Strings.elderlyForm.errors;

export type ElderlyFormValues = {
  fullName: string;
  /** As typed or picked, MM/DD/YYYY. */
  birthDate: string;
  gender: Gender | null;
  phone: string;
};

export type ElderlyFormField = keyof ElderlyFormValues;
export type ElderlyFormErrors = Partial<Record<ElderlyFormField, string>>;

/** 'draft' = only the name is required; 'complete' = name, birth date and gender. */
export type ElderlySaveMode = 'draft' | 'complete';

export const EMPTY_ELDERLY_FORM: ElderlyFormValues = { fullName: '', birthDate: '', gender: null, phone: '' };

// --- birth date -------------------------------------------------------------------

const MM_DD_YYYY = /^(\d{2})\/(\d{2})\/(\d{4})$/;
const DATE_DIGITS = 8; // MMDDYYYY

/** Inserts the slashes while typing: "0412195" -> "04/12/195". */
export function maskDateInput(raw: string): string {
  const digits = raw.replace(/\D/g, '').slice(0, DATE_DIGITS);
  const parts = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4)].filter(Boolean);
  return parts.join('/');
}

/** Local calendar date for MM/DD/YYYY, or null when it is not a real date. */
export function parseDateInput(text: string): Date | null {
  const match = MM_DD_YYYY.exec(text.trim());
  if (!match) return null;
  const [month, day, year] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(year, month - 1, day);
  const real = date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
  return real ? date : null;
}

const pad2 = (n: number) => String(n).padStart(2, '0');

export function formatDateInput(date: Date): string {
  return `${pad2(date.getMonth() + 1)}/${pad2(date.getDate())}/${date.getFullYear()}`;
}

/** YYYY-MM-DD for the API (the calendar date, not shifted by the timezone). */
export function toIsoDate(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function startOfToday(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

/** Earliest birth date the backend accepts (ELDERLY_MAX_AGE_YEARS ago). */
export function earliestBirthDate(): Date {
  const today = startOfToday();
  return new Date(today.getFullYear() - AppConfig.elderlyMaxAgeYears, today.getMonth(), today.getDate());
}

export function latestBirthDate(): Date {
  return startOfToday();
}

export function ageFromBirthDate(birth: Date, today: Date = startOfToday()): number {
  const hadBirthday =
    today.getMonth() > birth.getMonth() ||
    (today.getMonth() === birth.getMonth() && today.getDate() >= birth.getDate());
  return today.getFullYear() - birth.getFullYear() - (hadBirthday ? 0 : 1);
}

/** Valid birth date in range, or null. */
export function validBirthDate(text: string): Date | null {
  const date = parseDateInput(text);
  if (!date || date > latestBirthDate() || date < earliestBirthDate()) return null;
  return date;
}

// --- phone ------------------------------------------------------------------------

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

// --- whole form -------------------------------------------------------------------

export function validateElderlyForm(values: ElderlyFormValues, mode: ElderlySaveMode): ElderlyFormErrors {
  const errors: ElderlyFormErrors = {};
  const name = values.fullName.trim();
  if (!name) errors.fullName = E.nameRequired;
  else if (name.length < AppConfig.elderlyNameMinLength) errors.fullName = E.nameTooShort(AppConfig.elderlyNameMinLength);
  else if (name.length > AppConfig.elderlyNameMaxLength) errors.fullName = E.nameTooLong(AppConfig.elderlyNameMaxLength);

  // Optional fields are still checked when filled in: the backend rejects them in a draft too.
  if (values.birthDate.trim()) {
    if (!validBirthDate(values.birthDate)) errors.birthDate = E.birthDateInvalid;
  } else if (mode === 'complete') {
    errors.birthDate = E.birthDateRequired;
  }
  if (mode === 'complete' && !values.gender) errors.gender = E.genderRequired;
  if (values.phone.trim() && !normalizeIdPhone(values.phone)) errors.phone = E.phoneInvalid;
  return errors;
}

/** Request body for a form that passed validateElderlyForm. Empty optional fields are left out. */
export function toElderlyIn(values: ElderlyFormValues): ElderlyIn {
  const birth = values.birthDate.trim() ? validBirthDate(values.birthDate) : null;
  const phone = values.phone.trim() ? normalizeIdPhone(values.phone) : null;
  return {
    full_name: values.fullName.trim(),
    ...(birth && { birth_date: toIsoDate(birth) }),
    ...(values.gender && { gender: values.gender }),
    ...(phone && { contact_phone: phone }),
  };
}

/** Backend 422 field (ElderlyIn key) -> form field, with the Indonesian message for it. */
export const SERVER_FIELD_ERRORS: Record<keyof ElderlyIn, { field: ElderlyFormField; message: string }> = {
  full_name: { field: 'fullName', message: E.nameInvalid },
  birth_date: { field: 'birthDate', message: E.birthDateInvalid },
  gender: { field: 'gender', message: E.genderRequired }, // only an unknown enum value reaches the server
  contact_phone: { field: 'phone', message: E.phoneInvalid },
};
