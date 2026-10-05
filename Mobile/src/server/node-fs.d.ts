// Minimal typing for the dev-only email driver (the project has no @types/node).
declare module 'node:fs/promises' {
  export function readFile(path: string, encoding: 'utf8'): Promise<string>;
  export function writeFile(path: string, data: string): Promise<void>;
}
