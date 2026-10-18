// Pairing-code validation, shared by the QR scanner and manual entry. Runs BEFORE anything is
// sent to the backend: a QR that is not a PillCare code (a URL, Wi-Fi config, JSON...) never
// leaves the phone.
//
// A device code is "PB-" + 8 uppercase hex digits: the emulator generates it with
// secrets.token_hex(4).upper() (SmartDevice/smart_pillbox/core/sync.py) and the backend with
// token_hex(4).upper() (Backend/app/core/security.py). The emulator's QR holds the bare code;
// the device contract's URI form "pillcare://device/PB-..." (docs/DEVICE_CONTRACT.md) is accepted too.

const CODE = /^PB-[0-9A-F]{8}$/;
const URI = /^pillcare:\/\/device\/([^/?#]+)\/?$/i;

/** Longest input worth parsing; anything longer is rejected without running the regexes. */
const MAX_PAYLOAD_LENGTH = 64;

/** The normalized device code ("PB-1A2B3C4D"), or null when `raw` is not a PillCare pairing code. */
export function parsePairingPayload(raw: string): string | null {
  const text = raw.trim();
  if (!text || text.length > MAX_PAYLOAD_LENGTH) return null;
  const candidate = (URI.exec(text)?.[1] ?? text).toUpperCase();
  return CODE.test(candidate) ? candidate : null;
}

export const PAIRING_CODE_HINT = 'Format kode: PB- diikuti 8 karakter (angka 0-9 dan huruf A-F), mis. PB-1A2B3C4D.';
