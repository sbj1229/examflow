// 실제 app.js를 실행하고 응답 순서를 제어하는 비동기 회귀 검사.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const response = data => ({ ok: true, json: async () => data });
function setup(route, state = 'awaiting_approval') {
  const elements = new Map();
  const element = () => ({ disabled: false, hidden: false, value: '', handlers: {},
    addEventListener(name, fn) { this.handlers[name] = fn; },
    append() {}, replaceChildren() {}, focus() {}, click() {} });
  const get = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
  const calls = [];
  const context = vm.createContext({ console,
    document: { getElementById: get, createElement: element, querySelectorAll: () => [] },
    fetch: async (url, options) => {
      if (url === '/api/health') return response({ model_mode: 'fixture' });
      calls.push({ url, options }); return route(url, options);
    }, setTimeout: () => 0, clearTimeout() {}, Blob, URL });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8'), context);
  context.run = { id: 'original', state, version: 1, events: [] };
  vm.runInContext('render(run)', context);
  return { get, calls, context, read: expr => vm.runInContext(expr, context) };
}

test('승인 중 새 요청·중복 승인·취소를 막고 완료 후 제어를 복구한다', async () => {
  const pending = deferred();
  const ui = setup(() => pending.promise);
  const approval = ui.get('approve').handlers.click();
  assert.equal(ui.get('submit').disabled, true);
  assert.equal(ui.get('cancel').disabled, true);
  await ui.get('request-form').handlers.submit({ preventDefault() {} });
  await ui.get('approve').handlers.click();
  await ui.get('cancel').handlers.click();
  assert.equal(ui.calls.length, 1);
  pending.resolve(response({ ...ui.context.run, state: 'confirmed' }));
  await approval;
  assert.equal(ui.read('current.id'), 'original');
  assert.equal(ui.read('current.state'), 'confirmed');
  assert.equal(ui.get('submit').disabled, false);
});

test('취소 이전에 시작한 폴링 응답이 취소 완료를 되돌리지 않는다', async () => {
  const pending = deferred();
  const ui = setup(url => url.endsWith('/cancel')
    ? response({ id: 'original', state: 'cancelled', version: 1, events: [] })
    : pending.promise, 'checking');
  const poll = ui.read('poll()');
  await ui.get('cancel').handlers.click();
  pending.resolve(response({ ...ui.context.run, state: 'checking' }));
  await poll;
  assert.equal(ui.read('current.state'), 'cancelled');
  assert.equal(ui.get('submit').disabled, false);
});

test('승인 응답 유실 뒤 같은 실행을 조회하고 새 요청을 생성하지 않는다', async () => {
  const ui = setup(url => {
    if (url.endsWith('/approve')) throw new Error('응답 유실');
    return response({ id: 'original', state: 'confirmed', version: 1, events: [] });
  });
  await ui.get('approve').handlers.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.read('current.state'), 'confirmed');
  assert.deepEqual(ui.calls.map(x => x.url), ['/api/runs/original/approve', '/api/runs/original']);
  assert.equal(ui.get('submit').disabled, false);
});
