const assert = require('assert');
const Module = require('node:module');
const test = require('node:test');

const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return {};
  return originalLoad.call(this, request, parent, isMain);
};

const { childRelationCounts, diagramIndex, modelNeighborhoodIds } = require('../out/parser');

test.after(() => {
  Module._load = originalLoad;
});

test('a model lens keeps descendants and their parents, excluding the root parents', () => {
  const index = {
    scannedAt: 0,
    apps: [
      {
        name: 'shop',
        path: '/shop',
        models: [
          {
            name: 'Order',
            appName: 'shop',
            filePath: '/proj/shop/models.py',
            lineNumber: 10,
            baseClasses: ['billing.Account'],
            inheritedFields: [
              { name: 'company', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'org.Company', lineNumber: 2 },
            ],
            fields: [
              { name: 'user', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'auth.User', lineNumber: 12 },
              { name: 'coupon', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'billing.Coupon', lineNumber: 13 },
              { name: 'tags', type: 'ManyToManyField', args: '', isRelation: true, relatedModel: 'Tag', throughModel: 'OrderTag', lineNumber: 14 },
              { name: 'note', type: 'CharField', args: '', isRelation: false, lineNumber: 15 },
              { name: 'missing', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'other.Gone', lineNumber: 16 },
            ],
          },
          {
            name: 'Coupon',
            appName: 'shop',
            filePath: '/proj/shop/billing.py',
            lineNumber: 1,
            baseClasses: [],
            fields: [
              { name: 'campaign', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Campaign', lineNumber: 3 },
            ],
          },
          {
            name: 'Campaign',
            appName: 'shop',
            filePath: '/proj/shop/campaigns.py',
            lineNumber: 1,
            baseClasses: [],
            fields: [
              { name: 'region', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Region', lineNumber: 3 },
            ],
          },
          {
            name: 'Region',
            appName: 'shop',
            filePath: '/proj/shop/regions.py',
            lineNumber: 1,
            baseClasses: ['models.Model'],
            fields: [],
          },
          {
            name: 'Invoice',
            appName: 'shop',
            filePath: '/proj/shop/invoices.py',
            lineNumber: 4,
            baseClasses: [],
            fields: [
              { name: 'order', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Order', lineNumber: 6 },
              { name: 'customer', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Customer', lineNumber: 7 },
            ],
          },
          {
            name: 'Customer',
            appName: 'shop',
            filePath: '/proj/shop/customers.py',
            lineNumber: 1,
            baseClasses: [],
            fields: [
              { name: 'country', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Country', lineNumber: 3 },
            ],
          },
          {
            name: 'Country',
            appName: 'shop',
            filePath: '/proj/shop/countries.py',
            lineNumber: 1,
            baseClasses: ['models.Model'],
            fields: [],
          },
          {
            name: 'Refund',
            appName: 'shop',
            filePath: '/proj/shop/refunds.py',
            lineNumber: 1,
            baseClasses: [],
            fields: [
              { name: 'customer', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Customer', lineNumber: 3 },
            ],
          },
          {
            name: 'Payment',
            appName: 'shop',
            filePath: '/proj/shop/payments.py',
            lineNumber: 1,
            baseClasses: [],
            fields: [
              { name: 'invoice', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Invoice', lineNumber: 3 },
            ],
          },
          {
            name: 'OrderTag',
            appName: 'shop',
            filePath: '/proj/shop/tags.py',
            lineNumber: 1,
            baseClasses: [],
            fields: [
              { name: 'order', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Order', lineNumber: 3 },
              { name: 'tag', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Tag', lineNumber: 4 },
            ],
          },
          {
            name: 'Tag',
            appName: 'shop',
            filePath: '/proj/shop/tags.py',
            lineNumber: 20,
            baseClasses: [],
            fields: [],
          },
          {
            name: 'Account',
            appName: 'shop',
            filePath: '/proj/shop/account.py',
            lineNumber: 1,
            baseClasses: ['models.Model'],
            fields: [],
          },
          {
            name: 'RushOrder',
            appName: 'shop',
            filePath: '/proj/shop/rush.py',
            lineNumber: 1,
            baseClasses: ['Order', 'AuditMixin'],
            fields: [],
          },
          {
            name: 'AuditMixin',
            appName: 'shop',
            filePath: '/proj/shop/audit.py',
            lineNumber: 1,
            baseClasses: ['models.Model'],
            fields: [],
          },
          {
            name: 'AuditLog',
            appName: 'shop',
            filePath: '/proj/shop/audit.py',
            lineNumber: 20,
            baseClasses: ['AuditMixin'],
            fields: [],
          },
          {
            name: 'Product',
            appName: 'shop',
            filePath: '/proj/shop/products.py',
            lineNumber: 1,
            baseClasses: [],
            fields: [
              { name: 'sku', type: 'CharField', args: '', isRelation: false, lineNumber: 2 },
            ],
          },
        ],
      },
      {
        name: 'auth',
        path: '/auth',
        models: [
          {
            name: 'User',
            appName: 'auth',
            filePath: '/proj/auth/models.py',
            lineNumber: 1,
            baseClasses: ['models.Model'],
            fields: [
              { name: 'profile', type: 'OneToOneField', args: '', isRelation: true, relatedModel: 'Profile', lineNumber: 4 },
            ],
          },
          {
            name: 'Profile',
            appName: 'auth',
            filePath: '/proj/auth/models.py',
            lineNumber: 30,
            baseClasses: [],
            fields: [],
          },
        ],
      },
      {
        name: 'org',
        path: '/org',
        models: [
          {
            name: 'Company',
            appName: 'org',
            filePath: '/proj/org/models.py',
            lineNumber: 1,
            baseClasses: [],
            fields: [],
          },
        ],
      },
    ],
  };
  // Invoice points at Customer, so Customer is a parent of a child and stays.
  // Country is Customer's parent and Refund points at Customer; neither is
  // expanded. User, Coupon, Tag, Company, and Account are Order's own parents.
  assert.deepEqual(modelNeighborhoodIds(index, '/proj/shop/models.py', 10).sort(), [
    'shop/Customer',
    'shop/Invoice',
    'shop/Order',
    'shop/OrderTag',
    'shop/Payment',
    'shop/RushOrder',
  ]);
  assert.deepEqual(modelNeighborhoodIds(index, '/proj/shop/invoices.py', 4).sort(), [
    'shop/Invoice',
    'shop/Payment',
  ]);
  assert.deepEqual(modelNeighborhoodIds(index, '/proj/shop/campaigns.py', 1).sort(), [
    'auth/User',
    'org/Company',
    'shop/Account',
    'shop/Campaign',
    'shop/Coupon',
    'shop/Customer',
    'shop/Invoice',
    'shop/Order',
    'shop/OrderTag',
    'shop/Payment',
    'shop/RushOrder',
    'shop/Tag',
  ]);
  assert.equal(modelNeighborhoodIds(index, '/proj/shop/models.py', 99), undefined);

  const counts = childRelationCounts(index);
  const byName = new Map();
  for (const app of index.apps) for (const model of app.models) byName.set(model.name, model);
  // Only fields pointing straight here. Order's own user, coupon, tags, and
  // company fields are relations to its parents, so they are not counted.
  assert.equal(counts.get(byName.get('Order')), 2);
  assert.equal(counts.get(byName.get('Coupon')), 1);
  assert.equal(counts.get(byName.get('Campaign')), 1);
  assert.equal(counts.get(byName.get('Invoice')), 1);
  assert.equal(counts.get(byName.get('Payment')), 0);
  assert.equal(counts.get(byName.get('Product')), 0);
  assert.equal(counts.get(byName.get('Tag')), 2);
  assert.equal(counts.get(byName.get('User')), 1);
  assert.equal(counts.get(byName.get('Company')), 1);
});

test('a model lens opens a parent on its children, not on the models it points at', () => {
  const index = {
    scannedAt: 0,
    apps: [
      {
        name: 'shop',
        path: '/shop',
        models: [
          {
            name: 'Order',
            appName: 'shop',
            filePath: '/proj/shop/models.py',
            lineNumber: 10,
            baseClasses: [],
            fields: [
              { name: 'user', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'auth.User', lineNumber: 12 },
              { name: 'coupon', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'billing.Coupon', lineNumber: 13 },
              { name: 'note', type: 'CharField', args: '', isRelation: false, lineNumber: 14 },
              { name: 'missing', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'other.Gone', lineNumber: 15 },
            ],
          },
          {
            name: 'Coupon',
            appName: 'shop',
            filePath: '/proj/shop/billing.py',
            lineNumber: 1,
            baseClasses: [],
            fields: [],
          },
        ],
      },
      {
        name: 'auth',
        path: '/auth',
        models: [
          {
            name: 'User',
            appName: 'auth',
            filePath: '/proj/auth/models.py',
            lineNumber: 1,
            baseClasses: ['models.Model'],
            fields: [],
          },
        ],
      },
    ],
  };
  assert.deepEqual(modelNeighborhoodIds(index, '/proj/shop/models.py', 10), ['shop/Order']);
  assert.deepEqual(modelNeighborhoodIds(index, '/proj/auth/models.py', 1).sort(), [
    'auth/User',
    'shop/Coupon',
    'shop/Order',
  ]);
});

test('a proxy is left off the diagram and its relations land on the concrete table', () => {
  const index = {
    scannedAt: 0,
    apps: [
      {
        name: 'shop',
        path: '/shop',
        models: [
          {
            name: 'Order',
            appName: 'shop',
            filePath: '/proj/shop/models.py',
            lineNumber: 10,
            baseClasses: ['models.Model'],
            meta: {},
            fields: [],
            inheritedFields: [],
          },
          {
            name: 'OrderProps',
            appName: 'shop',
            filePath: '/proj/shop/props.py',
            lineNumber: 4,
            baseClasses: ['Order'],
            meta: { proxy: 'True' },
            fields: [],
            inheritedFields: [],
          },
          {
            name: 'OrderProxy',
            appName: 'shop',
            filePath: '/proj/shop/proxy.py',
            lineNumber: 8,
            baseClasses: ['OrderProps', 'Order'],
            meta: { proxy: 'True' },
            fields: [],
            inheritedFields: [],
          },
          {
            name: 'Note',
            appName: 'shop',
            filePath: '/proj/shop/notes.py',
            lineNumber: 2,
            baseClasses: ['models.Model'],
            meta: {},
            fields: [
              { name: 'order', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'OrderProxy', lineNumber: 4 },
            ],
            inheritedFields: [],
          },
          {
            name: 'Legacy',
            appName: 'shop',
            filePath: '/proj/shop/legacy.py',
            lineNumber: 1,
            baseClasses: ['models.Model'],
            meta: { managed: 'False' },
            fields: [
              { name: 'order', type: 'ForeignKey', args: '', isRelation: true, relatedModel: 'Order', lineNumber: 3 },
            ],
            inheritedFields: [],
          },
        ],
      },
    ],
  };

  assert.deepEqual(modelNeighborhoodIds(index, '/proj/shop/models.py', 10).sort(), [
    'shop/Legacy',
    'shop/Note',
    'shop/Order',
  ]);
  assert.deepEqual(modelNeighborhoodIds(index, '/proj/shop/proxy.py', 8).sort(), [
    'shop/Legacy',
    'shop/Note',
    'shop/Order',
  ]);

  const counts = childRelationCounts(index);
  const order = index.apps[0].models.find((model) => model.name === 'Order');
  const proxy = index.apps[0].models.find((model) => model.name === 'OrderProxy');
  assert.equal(counts.get(order), 2);
  assert.equal(counts.get(proxy), 0);

  const diagram = diagramIndex(index);
  const names = diagram.apps[0].models.map((model) => model.name).sort();
  assert.deepEqual(names, ['Legacy', 'Note', 'Order']);
  const note = diagram.apps[0].models.find((model) => model.name === 'Note');
  assert.equal(note.fields[0].relatedModel, 'shop.Order');
  const legacy = diagram.apps[0].models.find((model) => model.name === 'Legacy');
  assert.equal(legacy.meta.managed, 'False');
});
