// Start tools/interface/preview.py with HR_UI_COMPANY_DOCUMENT_FIXTURES=1,
// HR_UI_DB=/private/tmp/hr-interface/company-documents.sqlite3, HR_UI_PORT=8791,
// HR_UI_STATE=/private/tmp/hr-interface/company-documents-state.json.
const {chromium} = require('playwright');
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const base = process.env.HR_UI_URL || 'http://127.0.0.1:8791';
const output = process.env.HR_UI_OUTPUT || '/private/tmp/hr-interface/company-documents';
const state = JSON.parse(fs.readFileSync(process.env.HR_UI_STATE || '/private/tmp/hr-interface/company-documents-state.json', 'utf8'));
const checks = [], errors = [];
fs.mkdirSync(output, {recursive: true});

async function load(page, route) {
  const response = await page.goto(base + route);
  assert.equal(response.status(), 200, route);
  await page.locator('.cd-page, .cd-dashboard').first().waitFor();
  await page.evaluate(() => document.fonts.ready);
}

async function layout(page, role, view, width, dark) {
  await page.setViewportSize({width, height: 950});
  await page.evaluate(d => {
    document.documentElement.classList.toggle('dark', d);
    document.body.classList.toggle('dark', d);
  }, dark);
  await page.waitForTimeout(250);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${role} ${view} ${width}: page overflow`);
  assert.ok(await page.locator('.cd-page, .cd-dashboard').first().evaluate(e => e.scrollWidth <= e.clientWidth + 1), `${role} ${view} ${width}: component overflow`);
  const title = page.locator('.cd-heading h1, #cd-dashboard-title').first();
  assert.ok(await title.isVisible());
  const secondary = page.locator('.cd-page .neutron-secondary-action').first();
  if (await secondary.count()) {
    const style = await secondary.evaluate(e => ({height: e.getBoundingClientRect().height, before: getComputedStyle(e, '::before').content, border: getComputedStyle(e).borderTopWidth}));
    assert.equal(style.height, 32);
    assert.equal(style.before, 'none');
    assert.equal(style.border, '1px');
  }
  checks.push({role, view, width, dark});
}

(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  const contexts = {};
  try {
    for (const [role, actor] of [['admin', 'zeyu+ui-admin@neutron.sg'], ['hr', 'zeyu+ui-2@neutron.sg'], ['employee', 'zeyu+ui-0@neutron.sg']]) {
      const context = await browser.newContext({viewport: {width: 1440, height: 950}, extraHTTPHeaders: {'X-HR-UI-Actor': actor}});
      contexts[role] = context;
      const page = await context.newPage();
      page.on('pageerror', error => errors.push({role, message: error.message}));
      for (const [view, route] of [['library', '/employee/company-documents/'], ['detail', `/employee/company-documents/${state.document}/`], ...(role === 'employee' ? [['dashboard', '/my/']] : [['form', '/employee/company-documents/new/']])]) {
        await load(page, route);
        for (const width of [1440, 1024, 390]) {
          for (const dark of [false, true]) {
            await layout(page, role, view, width, dark);
            if ((width === 1440 && !dark && role !== 'admin') || (width === 390 && dark && role !== 'admin')) {
              await page.screenshot({path: path.join(output, `${role}-${view}-${width}-${dark ? 'dark' : 'light'}.png`), fullPage: true});
            }
          }
        }
        console.log('PASS layouts', role, view);
      }
      await load(page, '/employee/company-documents/');
      assert.equal(await page.getByRole('link', {name: 'Add document', exact: true}).count(), role === 'employee' ? 0 : 1);
      assert.equal(await page.locator('#cd-state').count(), role === 'employee' ? 0 : 1);
      await page.locator('#cd-search').focus();
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'cd-category');
      await page.locator('#cd-category').selectOption('insurance');
      await page.getByRole('button', {name: 'Apply', exact: true}).click();
      await page.waitForURL('**/company-documents/?**');
      assert.equal(await page.locator('.cd-card h2').filter({hasText: 'Your insurance guide'}).count(), 1);
      assert.equal(await page.locator('.cd-card h2').filter({hasText: 'Expense claim form'}).count(), 0);
      await page.locator('#cd-search').fill('no matching synthetic document');
      await page.getByRole('button', {name: 'Apply', exact: true}).click();
      await page.locator('.cd-empty').waitFor();
      console.log('PASS filters and controls', role);
    }

    const hr = contexts.hr.pages()[0], employee = contexts.employee.pages()[0];
    await load(employee, '/my/');
    await employee.setViewportSize({width: 1440, height: 950});
    await employee.locator('.sideboxmain[data-menu="Employee"]').hover();
    const sidebarLink = employee.locator('#sidebarFlyoutList a').filter({hasText: 'Company documents'});
    await sidebarLink.waitFor({state: 'visible'});
    await sidebarLink.click();
    await employee.waitForURL(base + '/employee/company-documents/');
    await employee.locator('.cd-page h1').filter({hasText: 'Company documents'}).waitFor();
    assert.equal(await employee.locator('#ohMainContent').count(), 1);
    checks.push({name: 'employee sidebar navigates to complete Company documents library through HTMX'});

    await load(hr, `/employee/company-documents/${state.document}/`);
    const seededFileURL = await hr.locator('.cd-files a').filter({hasText: 'Download'}).first().getAttribute('href');
    const seededPDF = await contexts.hr.request.get(base + seededFileURL);
    assert.equal(seededPDF.status(), 200);
    assert.match(seededPDF.headers()['cache-control'], /no-store/);
    const buffer = await seededPDF.body();
    assert.equal(buffer.subarray(0, 5).toString(), '%PDF-');
    await load(hr, '/employee/company-documents/new/');
    const title = `Browser QA shared guide ${Date.now()}`;
    await hr.locator('#id_title').fill(title);
    await hr.locator('#id_category').selectOption('guides');
    await hr.locator('#id_files').setInputFiles({name: 'Browser guide.pdf', mimeType: 'application/pdf', buffer});
    await hr.locator('.cd-form button[value=publish]').click();
    await hr.waitForURL(/company-documents\/\d+\/$/);
    const documentRoute = new URL(hr.url()).pathname;
    assert.equal(await hr.locator('.cd-heading h1').innerText(), title);
    await load(employee, documentRoute);
    const originalFileURL = await employee.locator('.cd-files a').filter({hasText: 'Download'}).getAttribute('href');
    assert.equal((await contexts.employee.request.get(base + originalFileURL)).status(), 200);
    assert.equal(await employee.getByRole('link', {name: 'Edit document', exact: true}).count(), 0);

    await hr.getByRole('link', {name: 'Edit document', exact: true}).click();
    const replacedID = await hr.locator('#id_replace_file option').last().getAttribute('value');
    await hr.locator('#id_replace_file').selectOption(replacedID);
    await hr.locator('#id_files').setInputFiles({name: 'Revised browser guide.pdf', mimeType: 'application/pdf', buffer});
    await hr.locator('.cd-form button[value=publish]').click();
    await hr.waitForURL(base + documentRoute);
    await hr.getByRole('heading', {name: 'Previous file editions'}).waitFor();
    assert.equal((await contexts.employee.request.get(base + originalFileURL)).status(), 404);
    assert.equal((await contexts.hr.request.get(base + originalFileURL)).status(), 200);
    await load(employee, documentRoute);
    assert.match(await employee.locator('.cd-files').innerText(), /Revised browser guide/);
    await hr.locator('button[value=unpublish]').click();
    await hr.waitForURL(base + documentRoute);
    assert.equal((await contexts.employee.request.get(base + documentRoute)).status(), 404);
    await hr.locator('button[value=archive]').click();
    await hr.waitForURL(base + documentRoute);
    assert.match(await hr.locator('.cd-heading p').innerText(), /Archived/);
    checks.push({name: 'HR publishes, employee downloads, replacement keeps HR history, unpublish revokes, archive retains files'});
    console.log('PASS publishing lifecycle');
    assert.deepEqual(errors, []);
  } catch (error) {
    for (const [role, context] of Object.entries(contexts)) {
      const page = context.pages().at(-1);
      if (page) await page.screenshot({path: path.join(output, `failure-${role}.png`)}).catch(() => {});
    }
    throw error;
  } finally {
    fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify({checks, errors}, null, 2));
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
