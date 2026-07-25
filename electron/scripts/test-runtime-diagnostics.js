const assert = require('assert')
const { redactDiagnosticText } = require('../runtimeDiagnostics')

const raw = [
  'api_key=super-secret-value',
  'Authorization: Bearer abc.def.ghi',
  '{"token":"token-value","safe":"visible"}',
  'https://example.test/path?access_token=query-secret&ok=1',
  'sk_1234567890abcdefghijklmnop',
].join('\n')
const clean = redactDiagnosticText(raw)

for (const secret of ['super-secret-value', 'abc.def.ghi', 'token-value', 'query-secret', 'sk_1234567890abcdefghijklmnop']) {
  assert(!clean.includes(secret), `secret was not redacted: ${secret}`)
}
assert(clean.includes('"safe":"visible"'))
console.log('Runtime diagnostic redaction verified.')
