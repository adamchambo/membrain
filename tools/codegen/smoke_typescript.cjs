// Run after compiling sdk/typescript into dist/ with the pinned TypeScript compiler.
const assert = require('node:assert/strict');
const sdk = require('../../sdk/typescript/dist/index.js');
for (const raw of [{}, {title: null}, {note: null}, {title: 'Updated'}]) {
  const encoded = JSON.stringify(sdk.ResourcePatchToJSON(sdk.ResourcePatchFromJSON(raw)));
  assert.deepEqual(JSON.parse(encoded), raw);
}
for (const raw of [{detail: 'Invalid profile'}, {detail: [{loc: ['body', 0], msg: 'Invalid', type: 'value_error'}]}]) {
  const encoded = JSON.stringify(sdk.ValidationErrorResponseToJSON(sdk.ValidationErrorResponseFromJSON(raw)));
  assert.deepEqual(JSON.parse(encoded), raw);
}
const client = new sdk.CapturesApi(new sdk.Configuration({basePath: 'http://127.0.0.1:8000'}));
assert.equal(typeof client.ingestCapture, 'function');
console.log('TypeScript SDK: client construction, omitted/null PATCH fields, validation unions passed.');
