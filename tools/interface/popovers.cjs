// Local UI regression coverage using existing synthetic records and list filters.
// HR_UI_CREDENTIALS may point to the local username/password fixture file.
// Otherwise use the preview server's HR_UI_ACTOR header (admin by default).
const {chromium} = require('playwright');
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');

const base = process.env.HR_UI_URL || 'http://127.0.0.1:8768';
const output = process.env.HR_UI_OUTPUT || '/private/tmp/hr-interface/popovers';
const credentials = process.env.HR_UI_CREDENTIALS
    ? [...fs.readFileSync(process.env.HR_UI_CREDENTIALS, 'utf8').matchAll(/username: (\S+)\n  password: (\S+)/g)].map(m => [m[1], m[2]])
    : null;
const roles = credentials ? [['admin', 0], ['hr-manager', 2], ['employee', 1]] : [['preview', null]];
const checks = [];
const errors = [];
fs.mkdirSync(output, {recursive: true});

(async () => {
    const browser = await chromium.launch({channel: 'chrome', headless: true});
    try {
        for (const [role, index] of roles) {
            const context = await browser.newContext({viewport: {width: 1440, height: 1000},
                extraHTTPHeaders: credentials ? {} : {'X-HR-UI-Actor': process.env.HR_UI_ACTOR || 'zeyu+ui-admin@neutron.sg'}});
            const page = await context.newPage();
            page.on('pageerror', error => errors.push({role, url: page.url(), message: error.message}));
            const check = async (name, fn) => {
                try { await fn(); } catch (error) {
                    console.error('FAIL', role, name);
                    await shot('failure');
                    throw error;
                }
                checks.push({role, name});
                console.log('PASS', role, name);
            };
            const go = async url => {
                const response = await page.goto(base + url);
                assert.equal(response.status(), 200, url);
                await page.waitForTimeout(650); // HTMX navigation fragments and Select2 initialization.
            };
            const theme = async dark => {
                await page.evaluate(value => {
                    document.body.classList.toggle('dark', value);
                    document.documentElement.classList.toggle('dark', value);
                }, dark);
                await page.waitForTimeout(100);
            };
            const shot = name => page.screenshot({path: path.join(output, role + '-' + name + '.png')});
            if (credentials) {
                await go('/login/');
                await page.locator('#username').fill(credentials[index][0]);
                await page.locator('#password').fill(credentials[index][1]);
                await Promise.all([page.waitForNavigation(), page.locator('button[type=submit]').click()]);
            }
            await go('/dashboard/');
            const sidebarPaths = await page.locator('#sidebar a[href]').evaluateAll(links =>
                [...new Set(links.map(link => link.getAttribute('href')).filter(href => href?.startsWith('/') && !href.startsWith('/logout')))]);

            await check('queue metrics fit one surface and setup rings have clearance', async () => {
                if ((index === 0 || index === null) && !(await page.locator('.hcl-circle-active').count())) {
                    // DEBUG-only preview keeps this check meaningful after setup
                    // completes or the fixture user dismisses the real checklist.
                    await go('/dashboard/?preview_checklist=1');
                    assert.equal(await page.locator('.hcl-circle-active').count(), 1);
                }
                const queue = page.locator('.md-pending-grid');
                if (await queue.count()) {
                    const measurements = await queue.evaluate(grid => {
                        const cells = [...grid.children];
                        return {columns: getComputedStyle(grid).gridTemplateColumns.split(' ').filter(width => parseFloat(width) > 0).length,
                            cells: cells.map(cell => ({width: cell.clientWidth, shadow: getComputedStyle(cell).boxShadow,
                                overflow: cell.scrollWidth > cell.clientWidth}))};
                    });
                    assert.equal(measurements.columns, measurements.cells.length);
                    assert.ok(measurements.cells.every(cell => cell.width > 130 && cell.shadow === 'none' && !cell.overflow));
                    await queue.locator('a').first().hover();
                    assert.equal(await queue.locator('a').first().evaluate(e => getComputedStyle(e).boxShadow), 'none');
                }
                const active = page.locator('.hcl-circle-active');
                if (await active.count()) {
                    assert.ok(await active.evaluate(circle => circle.getBoundingClientRect().top - circle.closest('.hcl-steps').getBoundingClientRect().top >= 4));
                    assert.ok(await page.locator('.hcl-step').evaluateAll(steps => steps.every(step => step.clientWidth >= 88)));
                }
                for (const dark of [false, true]) {
                    await theme(dark);
                    await shot('dashboard-' + (dark ? 'dark' : 'light'));
                }
                await theme(false);
            });

            await check('notification interior clicks, glass plane, keyboard and outside dismissal', async () => {
                const bell = page.locator('#notificationBell');
                const panel = page.locator('#notificationPanel');
                await bell.click();
                await panel.locator('h2').click(); // Non-focusable content used to dismiss before click.
                assert.equal(await panel.isVisible(), true);
                assert.equal(await page.locator('#mainHeader').evaluate(e => getComputedStyle(e).backdropFilter), 'none');
                for (const dark of [false, true]) {
                    await theme(dark);
                    assert.match(await panel.evaluate(e => getComputedStyle(e).backdropFilter), /blur\(20px\)/);
                    assert.notEqual(await panel.evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');
                    await shot('notifications-' + (dark ? 'dark' : 'light'));
                }
                await page.locator('[aria-label="Close notifications"]').click();
                assert.equal(await panel.isVisible(), false);
                await bell.focus();
                await page.keyboard.press('ArrowDown');
                assert.equal(await panel.evaluate(e => e.contains(document.activeElement)), true);
                await page.keyboard.press('Escape');
                assert.equal(await bell.evaluate(e => e === document.activeElement), true);
                await bell.click();
                await page.locator('#ohMainContent h1').filter({visible: true}).first().click();
                assert.equal(await panel.isVisible(), false);
                await theme(false);
            });

            for (const type of ['neutron-profile-menu', 'neutron-quick-create']) {
                await check(type + ' opens by keyboard, stays on pointer entry and dismisses', async () => {
                    const wrapper = page.locator('.' + type);
                    const trigger = wrapper.locator(':scope > button');
                    await trigger.focus();
                    await page.keyboard.press('ArrowDown');
                    await wrapper.locator(':scope > .dropdown-content').hover();
                    assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
                    await page.keyboard.press('Escape');
                    assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
                    await trigger.click();
                    await page.locator('#ohMainContent h1').filter({visible: true}).first().click();
                    assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
                });
            }

            // Include the inline settings filter as well as every sidebar list.
            const paths = [...new Set([...sidebarPaths, '/settings/work-type-view/'])];
            for (const url of paths) {
                await go(url);
                const filters = page.locator('.dropdown-wrapper:has(> .oh-filter-dropdown)').filter({visible: true});
                const count = await filters.count();
                if (!count) continue;
                await check(url + ' filter interior controls and outside dismissal', async () => {
                    for (let i = 0; i < count; i++) {
                        const wrapper = filters.nth(i);
                        const trigger = wrapper.locator(':scope > [data-neutron-filter], :scope > button').first();
                        const panel = wrapper.locator(':scope > .dropdown-content');
                        await trigger.click();
                        assert.equal(await panel.isVisible(), true);
                        const accordion = panel.locator('.oh-accordion-header').first();
                        if (await accordion.count()) await accordion.click();
                        assert.equal(await panel.isVisible(), true);
                        const input = panel.locator('input[type=text]:not([readonly]):not([disabled]):not(.select2-search__field),input[type=number]:not([readonly]):not([disabled])').filter({visible: true}).first();
                        if (await input.count()) {
                            const previous = await input.inputValue();
                            await input.fill(await input.getAttribute('type') === 'number' ? '1' : 'Synthetic filter');
                            assert.equal(await panel.isVisible(), true);
                            await input.fill(previous);
                        }
                        await page.keyboard.press('Escape');
                        assert.equal(await panel.isVisible(), false);
                        await trigger.focus();
                        await page.keyboard.press('ArrowDown');
                        assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
                        await page.locator('#ohMainContent h1').filter({visible: true}).first().click();
                        assert.equal(await panel.isVisible(), false);
                    }
                });
            }

            await go('/employee/employee-view/');
            await check('employee filter searches and selects portaled options in both themes', async () => {
                const wrapper = page.locator('#filterDropdownWrapper');
                const trigger = wrapper.locator('[data-neutron-filter]');
                const panel = wrapper.locator(':scope > .dropdown-content');
                await trigger.click();
                const header = panel.locator('.oh-accordion-header').first();
                if (!(await panel.locator('input[name=employee_first_name]').isVisible())) await header.click();
                for (const dark of [false, true]) {
                    await theme(dark);
                    await panel.locator('select[name=country] + .select2 .select2-selection').click();
                    const portal = page.locator('body > .select2-container--open');
                    await portal.locator('.select2-search__field').fill('Singapore');
                    await shot('filter-options-' + (dark ? 'dark' : 'light'));
                    await portal.getByRole('option', {name: 'Singapore', exact: true}).click();
                    assert.equal(await panel.locator('select[name=country]').inputValue(), 'Singapore');
                    assert.equal(await panel.isVisible(), true);
                    await shot('filter-' + (dark ? 'dark' : 'light'));
                }
                // Escape first closes a nested select, then the parent filter.
                await panel.locator('select[name=country] + .select2 .select2-selection').click();
                await page.keyboard.press('Escape');
                assert.equal(await panel.isVisible(), true);
                assert.equal(await page.locator('body > .select2-container--open').count(), 0);
                await page.keyboard.press('Escape');
                assert.equal(await panel.isVisible(), false);
                await trigger.click();
                await panel.locator('select[name=country] + .select2 .select2-selection').click();
                await page.locator('#ohMainContent h1').filter({visible: true}).first().click();
                assert.equal(await panel.isVisible(), false);
                assert.equal(await page.locator('body > .select2-container--open').count(), 0);
                await trigger.focus();
                await page.keyboard.press('ArrowDown');
                await trigger.focus();
                await page.keyboard.press('Shift+Tab');
                await page.waitForTimeout(50);
                assert.equal(await panel.isVisible(), false);
            });
            await check('employee Apply sends selected filters through HTMX', async () => {
                const wrapper = page.locator('#filterDropdownWrapper');
                await wrapper.locator('[data-neutron-filter]').click();
                await wrapper.locator('input[name=employee_first_name]').fill('Casey');
                const response = page.waitForResponse(response => {
                    const url = new URL(response.url());
                    return url.pathname === '/employee/employees-list/' && url.searchParams.get('country') === 'Singapore'
                        && url.searchParams.get('employee_first_name') === 'Casey';
                });
                await wrapper.locator('#applyFilter').click();
                assert.equal((await response).status(), 200);
            });
            await context.close();
        }
        assert.deepEqual(errors, []);
    } finally {
        fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify({checks, errors}, null, 2));
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
