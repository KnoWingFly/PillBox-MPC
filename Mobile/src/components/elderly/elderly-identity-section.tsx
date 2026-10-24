import { AppConfig } from '@/config';
import { Strings } from '@/constants/strings';
import {
  ageFromBirthDate,
  earliestBirthDate,
  formatDateInput,
  latestBirthDate,
  maskDateInput,
  validBirthDate,
  type ElderlyFormErrors,
  type ElderlyFormField,
  type ElderlyFormValues,
} from '@/lib/elderly-form';
import type { Gender } from '@root/lib/elderly';

import { DateField } from '../form/date-field';
import { SegmentedChoice, type SegmentOption } from '../form/segmented-choice';
import { TextField } from '../form/text-field';
import { Card } from '../pillbox/ui';

const S = Strings.elderlyForm;

const GENDER_OPTIONS: readonly SegmentOption<Gender>[] = [
  { value: 'FEMALE', label: S.genderFemale },
  { value: 'MALE', label: S.genderMale },
];

function defaultPickerDate(): Date {
  const today = latestBirthDate();
  return new Date(today.getFullYear() - AppConfig.elderlyPickerDefaultAgeYears, today.getMonth(), today.getDate());
}

/** "Identitas & Relasi": name, birth date (with the computed age), gender and phone. */
export function ElderlyIdentitySection({
  values,
  errors,
  onChange,
  required,
}: {
  values: ElderlyFormValues;
  errors: ElderlyFormErrors;
  onChange: <K extends ElderlyFormField>(field: K, value: ElderlyFormValues[K]) => void;
  /** Mark birth date and gender as required (complete save). The name is always required. */
  required: boolean;
}) {
  const birth = validBirthDate(values.birthDate);

  return (
    <Card title={S.identitySection} icon="person-outline">
      <TextField
        label={S.fullName}
        required
        value={values.fullName}
        onChangeText={(text) => onChange('fullName', text)}
        placeholder={S.fullNamePlaceholder}
        autoCapitalize="words"
        maxLength={AppConfig.elderlyNameMaxLength}
        returnKeyType="next"
        error={errors.fullName}
      />
      <DateField
        label={S.birthDate}
        required={required}
        text={values.birthDate}
        onChangeText={(text) => onChange('birthDate', maskDateInput(text))}
        pickerValue={birth ?? defaultPickerDate()}
        onPick={(date) => onChange('birthDate', formatDateInput(date))}
        minimumDate={earliestBirthDate()}
        maximumDate={latestBirthDate()}
        placeholder={S.birthDatePlaceholder}
        hint={birth ? S.ageYears(ageFromBirthDate(birth)) : null}
        error={errors.birthDate}
      />
      <SegmentedChoice
        label={S.gender}
        required={required}
        options={GENDER_OPTIONS}
        value={values.gender}
        onChange={(gender) => onChange('gender', gender)}
        error={errors.gender}
      />
      <TextField
        label={S.phone}
        value={values.phone}
        onChangeText={(text) => onChange('phone', text)}
        placeholder={S.phonePlaceholder}
        keyboardType="phone-pad"
        textContentType="telephoneNumber"
        autoComplete="tel"
        error={errors.phone}
      />
    </Card>
  );
}
