import { useCallback, useRef, useState } from 'react';

import { Strings } from '@/constants/strings';
import {
  EMPTY_ELDERLY_FORM,
  SERVER_FIELD_ERRORS,
  toElderlyIn,
  validateElderlyForm,
  type ElderlyFormErrors,
  type ElderlyFormField,
  type ElderlyFormValues,
  type ElderlySaveMode,
} from '@/lib/elderly-form';
import { createElderly, validationFields, type ElderlyCreated } from '@root/lib/elderly';

export type SaveResult =
  | { ok: true; elderly: ElderlyCreated }
  /** `message` is for a toast; field problems are already in `errors`. */
  | { ok: false; message: string };

/** Form state and submit for "Tambah Profil Lansia". One request at a time (double taps are ignored). */
export function useCreateElderly() {
  const [values, setValues] = useState<ElderlyFormValues>(EMPTY_ELDERLY_FORM);
  const [errors, setErrors] = useState<ElderlyFormErrors>({});
  const [submitting, setSubmitting] = useState<ElderlySaveMode | null>(null);
  // A ref, not state: two taps in the same frame both see the old state.
  const inFlight = useRef(false);

  const setField = useCallback(<K extends ElderlyFormField>(field: K, value: ElderlyFormValues[K]) => {
    setValues((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => (prev[field] ? { ...prev, [field]: undefined } : prev));
  }, []);

  const save = useCallback(
    async (mode: ElderlySaveMode): Promise<SaveResult | null> => {
      if (inFlight.current) return null;
      const found = validateElderlyForm(values, mode);
      setErrors(found);
      if (Object.keys(found).length) return { ok: false, message: Strings.elderlyForm.fixErrors };

      inFlight.current = true;
      setSubmitting(mode);
      try {
        return { ok: true, elderly: await createElderly(toElderlyIn(values)) };
      } catch (err) {
        const server = validationFields(err);
        const mapped: ElderlyFormErrors = {};
        for (const key of Object.keys(server) as (keyof typeof SERVER_FIELD_ERRORS)[]) {
          const target = SERVER_FIELD_ERRORS[key];
          if (target) mapped[target.field] = target.message;
        }
        if (Object.keys(mapped).length) {
          setErrors(mapped);
          return { ok: false, message: Strings.elderlyForm.fixErrors };
        }
        return { ok: false, message: Strings.elderlyForm.saveFailed };
      } finally {
        inFlight.current = false;
        setSubmitting(null);
      }
    },
    [values],
  );

  return { values, errors, setField, save, submitting };
}
