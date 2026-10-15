const assert = require('node:assert/strict');
const test = require('node:test');

const { assembleName, recommendedMetaName, tablePart } = require('../../out/rules/indexNaming');

test('tablePart drops a leading ai_ and compresses long names', () => {
  assert.equal(tablePart('ai_events'), 'events');
  assert.equal(tablePart('shop_order'), 'shop_order');
  assert.equal(tablePart('ai_alpha_beta_gamma_delta_epsilon'), 'abgde');
  assert.equal(tablePart('ai_' + 'x'.repeat(30)), 'xxxx');
});

test('assembleName matches the MySQL schema editor', () => {
  assert.deepEqual(assembleName('idx', 'ai_company_users', ['company_id']), {
    name: 'idx_company_users_company',
    truncated: false,
  });
  assert.equal(
    assembleName('uniq', 'ai_company_users', ['company_id', 'status']).name,
    'uniq_company_users_company_status',
  );
  assert.equal(
    assembleName('idx', 'ai_events', ['company_id', 'is_campus_event', 'status']).name,
    'idx_events_company_is_campus_event_status',
  );
  assert.equal(
    assembleName('idx', 'ai_acl_product_permissions', ['role_id', 'key']).name,
    'idx_acl_product_permissions_role_key',
  );
  assert.equal(recommendedMetaName('unique', 'ai_events', ['uuid']).name, 'idx_uniq_ai_events');
});
