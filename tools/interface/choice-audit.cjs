// Read-only sidebar-page and form audit against the synthetic preview.
const {chromium} = require('playwright');
const fs = require('fs');
const path = require('path');
const base = process.env.HR_UI_URL || 'http://127.0.0.1:8791';
const output = process.env.HR_UI_OUTPUT || '/private/tmp/hr-interface/document-refinement';
const phase = process.argv[2] || 'before';
fs.mkdirSync(output, {recursive: true});

async function measure(page, context) {
  const fields = await page.locator('#ohMainContent select, .oh-modal--show select').evaluateAll(elements => elements.map(element => {
    const enhanced = window.jQuery && !!jQuery(element).data('select2');
    const selection = enhanced ? jQuery(element).data('select2').$selection[0] : element;
    const style = getComputedStyle(selection), rect = selection.getBoundingClientRect();
    return {name: element.name, id: element.id, classes: element.className, multiple: element.multiple,
      enhanced, visible: !!rect.width && !!rect.height && style.visibility !== 'hidden',
      height: rect.height, font: style.fontSize, background: style.backgroundColor, color: style.color,
      border: style.borderTopColor, radius: style.borderRadius, appearance: style.appearance};
  }));
  let popup = null;
  const selection = page.locator('.select2-selection:visible').first();
  if (await selection.count()) {
    await selection.click();
    const dropdown = page.locator('.select2-dropdown:visible').last();
    if (await dropdown.count()) popup = await dropdown.evaluate(element => {
      const style = getComputedStyle(element);
      return {background: style.backgroundColor, color: style.color, radius: style.borderRadius,
        border: style.borderTopColor, shadow: style.boxShadow};
    });
    await page.keyboard.press('Escape');
  }
  return {...context, fields, popup};
}

(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  const records = [], errors = [];
  try {
    await Promise.all([['admin', 'zeyu+ui-admin@neutron.sg'], ['hr', 'zeyu+ui-2@neutron.sg'], ['employee', 'zeyu+ui-0@neutron.sg']].map(async ([role, actor]) => {
      const context = await browser.newContext({viewport: {width: 1440, height: 1000}, extraHTTPHeaders: {'X-HR-UI-Actor': actor}});
      const page = await context.newPage();
      page.on('pageerror', error => errors.push({role, url: page.url(), message: error.message}));
      await page.goto(base + '/employee/company-documents/');
      const urls = await page.locator('#sidebar .sidebar-subnav-link[href], #sidebar a.sideboxmain[href]').evaluateAll(elements => [...new Set(elements.map(element => element.getAttribute('href')))].filter(url => url.startsWith('/') && !url.includes('logout')));
      for (const url of urls) {
        try {
          const response = await page.goto(base + url);
          await page.waitForTimeout(350);
          for (const dark of [false, true]) {
            await page.evaluate(value => {document.body.classList.toggle('dark', value); document.documentElement.classList.toggle('dark', value);}, dark);
            records.push(await measure(page, {role, url, status: response.status(), dark, surface: 'page'}));
          }
          console.log('AUDIT', role, url, records.at(-1).fields.length);
        } catch (error) {
          errors.push({role, url, message: error.message});
        }
      }
      // Inspect filters and create dialogs in each major application without saving.
      for (const url of ['/employee/employee-view/', '/leave/request-view/', '/payroll/view-reimbursement/', '/asset/asset-category-view/', '/recruitment/recruitment-view/']) {
        await page.goto(base + url);
        await page.waitForTimeout(450);
        const filter = page.locator('#ohMainContent [data-neutron-filter]').first();
        if (!await filter.count()) await page.waitForTimeout(500);
        if (await filter.count() && await filter.isVisible()) {
          await filter.click();
          await page.waitForTimeout(150);
          const wrapper = filter.locator('xpath=..');
          if (await wrapper.locator('.oh-accordion-header').count()) await wrapper.locator('.oh-accordion-header').first().click();
          for (const dark of [false, true]) {
            await page.evaluate(value => {document.body.classList.toggle('dark', value); document.documentElement.classList.toggle('dark', value);}, dark);
            records.push(await measure(page, {role, url, dark, surface: 'filter'}));
          }
          await page.keyboard.press('Escape');
        }
        const candidates = await page.locator('#ohMainContent [hx-get]').evaluateAll(elements => elements.filter(element => element.getAttribute('hx-get').match(/(?:create|new)(?:[-/]|$)/) && !element.closest('tr')).map(element => ({url: element.getAttribute('hx-get'), visible: !!element.getBoundingClientRect().width})));
        const candidate = candidates.find(item => item.visible && !item.url.includes('employee-view-new'));
        if (candidate) {
          const button = page.locator(`#ohMainContent [hx-get="${candidate.url}"]`).first();
          if (await button.isVisible()) {
            await button.click();
            await page.waitForTimeout(450);
            if (await page.locator('.oh-modal--show').count()) records.push(await measure(page, {role, url, surface: 'create'}));
            await page.keyboard.press('Escape');
          }
        }
      }
      await context.close();
    }));
  } finally {
    fs.writeFileSync(path.join(output, `${phase}.json`), JSON.stringify({records, errors}, null, 2));
    await browser.close();
  }
  console.log('SUMMARY', JSON.stringify({records: records.length, errors: errors.length}));
})().catch(error => {console.error(error); process.exitCode = 1;});
