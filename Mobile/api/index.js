const { createRequestHandler } = require('expo-server/adapter/vercel');

module.exports = createRequestHandler({
  build: require('node:path').join(process.cwd(), 'dist/server'),
});
