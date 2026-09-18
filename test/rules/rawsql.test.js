const assert = require('node:assert/strict');
const Module = require('node:module');
const test = require('node:test');

// Shim the `vscode` module — rules only touch it via type-only imports at
// build time; at runtime the plain `{}` shim is sufficient because none of
// the rule-check code paths call into a vscode.* runtime member.
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { rawSqlRules } = require('../../out/rules/rawsql');

test.after(() => {
  Module._load = originalLoad;
});

/** Build a fake `RuleContext` from a source string. */
function makeCtx(source) {
  const lines = source.split(/\r?\n/);
  return {
    document: null,
    lineCount: lines.length,
    lineAt(i) {
      return lines[i] ?? '';
    },
    windowBefore(i, n) {
      return lines.slice(Math.max(0, i - n), i);
    },
    windowAfter(i, n) {
      return lines.slice(i + 1, Math.min(lines.length, i + 1 + n));
    },
  };
}

/** Look up a rule by code, failing loudly when it is not registered. */
function ruleByCode(code) {
  const r = rawSqlRules.find((r) => r.meta.code === code);
  assert.ok(r, `rule ${code} must exist`);
  return r;
}

test('DOL041 flags both GUCs in a parameterized multi-statement SET', () => {
  const rule = ruleByCode('DOL041');
  const findings = rule.check(
    makeCtx(
      "cursor.execute('SET enable_seqscan = %s; SET enable_bitmapscan = %s', ['off', 'off'])",
    ),
  );
  assert.equal(findings.length, 2);
  assert.equal(findings[0].code, 'DOL041');
  assert.equal(findings[0].applicability, 'unsafe');
  assert.equal(findings[0].args.guc, 'enable_seqscan');
  assert.equal(findings[0].args.value, '%s');
  assert.equal(findings[1].args.guc, 'enable_bitmapscan');
});

test('DOL041 flags SET LOCAL and SESSION variants', () => {
  const rule = ruleByCode('DOL041');
  const local = rule.check(makeCtx('SET LOCAL enable_seqscan = off'));
  assert.equal(local.length, 1);
  assert.equal(local[0].messageId, 'local');
  const session = rule.check(
    makeCtx('cur.execute("SET SESSION enable_bitmapscan = off")'),
  );
  assert.equal(session.length, 1);
  assert.equal(session[0].messageId, 'connection');
});

test('DOL041 captures named DB-API placeholders completely', () => {
  const rule = ruleByCode('DOL041');
  const findings = rule.check(makeCtx('SET enable_seqscan = %(planner)s'));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].args.value, '%(planner)s');
});

test('DOL041 accepts the TO form and quoted values', () => {
  const rule = ruleByCode('DOL041');
  const findings = rule.check(
    makeCtx("SET enable_nestloop TO 'off'"),
  );
  assert.equal(findings.length, 1);
  assert.equal(findings[0].args.guc, 'enable_nestloop');
});

test('DOL041 flags plan_cache_mode and jit overrides', () => {
  const rule = ruleByCode('DOL041');
  const findings = rule.check(
    makeCtx('SET plan_cache_mode = force_generic_plan\nSET jit = off'),
  );
  assert.equal(findings.length, 2);
  assert.equal(findings[0].args.guc, 'plan_cache_mode');
  assert.equal(findings[1].args.guc, 'jit');
});

test('DOL041 matches without spaces around the equals sign', () => {
  const rule = ruleByCode('DOL041');
  const findings = rule.check(makeCtx('SET enable_hashjoin=off'));
  assert.equal(findings.length, 1);
  assert.equal(findings[0].args.value, 'off');
});

test('DOL041 ignores non-planner session settings', () => {
  const rule = ruleByCode('DOL041');
  assert.equal(rule.check(makeCtx("SET statement_timeout = '5s'")).length, 0);
  assert.equal(rule.check(makeCtx("SET search_path = 'public'")).length, 0);
  assert.equal(rule.check(makeCtx('SET work_mem = 65536')).length, 0);
  assert.equal(
    rule.check(makeCtx('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')).length,
    0,
  );
});

test('DOL041 ignores comment lines', () => {
  const rule = ruleByCode('DOL041');
  assert.equal(rule.check(makeCtx('# SET enable_seqscan = off  legacy')).length, 0);
  assert.equal(rule.check(makeCtx('-- SET enable_seqscan = off')).length, 0);
});

test('DOL041 stays quiet on ordinary SQL and ORM code', () => {
  const rule = ruleByCode('DOL041');
  const findings = rule.check(
    makeCtx(
      'qs = Order.objects.filter(customer__in=ids)\nrows = list(qs[:100])',
    ),
  );
  assert.equal(findings.length, 0);
});
