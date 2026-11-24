const fs = require('node:fs');
const path = require('node:path');

const engineFile = 'libquery_engine-rhel-openssl-3.0.x.so.node';
const generatedClientDir = path.resolve(
  path.dirname(require.resolve('@prisma/client/package.json')),
  '../../.prisma/client',
);
const source = path.join(generatedClientDir, engineFile);
const serverApiDir = path.resolve('dist/server/_expo/functions/api');

if (!fs.existsSync(source)) {
  throw new Error(`Prisma query engine is missing: ${source}`);
}
if (!fs.existsSync(serverApiDir)) {
  throw new Error(`Expo server API output is missing: ${serverApiDir}`);
}

fs.copyFileSync(source, path.join(serverApiDir, engineFile));
