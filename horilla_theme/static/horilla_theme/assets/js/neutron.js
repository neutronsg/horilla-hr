/* Shared feedback and keyboard behavior. One registration per full document. */
(function () {
    if (window.neutronInterface) return;
    window.neutronInterface = true;
    // Native details menus retain the server's exact permitted action markup.
    // Fixed positioning keeps them outside a scrollable table's clipping box.
    function positionMenu(menu) {
        const content = menu.querySelector('.neutron-action-menu-content');
        const rect = menu.querySelector('summary').getBoundingClientRect();
        content.style.left = Math.max(12, Math.min(innerWidth - 222, rect.right - 210)) + 'px';
        const height = content.getBoundingClientRect().height;
        content.style.top = (rect.bottom + height + 12 > innerHeight ? Math.max(12, rect.top - height - 6) : rect.bottom + 6) + 'px';
    }
    document.addEventListener('toggle', event => {
        const menu = event.target;
        if (!menu.matches?.('.neutron-action-menu') || !menu.open) return;
        document.querySelectorAll('.neutron-action-menu[open]').forEach(other => { if (other !== menu) other.open = false; });
        positionMenu(menu);
    }, true);
    function closeMenus() { document.querySelectorAll('.neutron-action-menu[open]').forEach(menu => { menu.open = false; }); }
    function reflectProfileTab(tab) {
        const profile = tab?.closest('.emp-profile-page');
        const label = profile?.querySelector('.neutron-profile-overflow-label');
        if (!label) return;
        label.dataset.defaultLabel ||= label.textContent;
        const secondary = Boolean(tab.closest('.neutron-profile-overflow'));
        label.textContent = secondary ? tab.dataset.tab : label.dataset.defaultLabel;
        label.closest('summary').classList.toggle('neutron-selected-overflow', secondary);
    }
    document.addEventListener('click', event => {
        reflectProfileTab(event.target.closest('button[data-tab]'));
        if (event.target.closest('[data-neutron-clear-search]')) {
            const search = document.querySelector('.navFilterForm input[name=search]');
            if (search) { search.value = ''; search.dispatchEvent(new Event('input', {bubbles: true})); search.focus(); }
        }
        if (!event.target.closest('.neutron-action-menu')) closeMenus();
        else if (event.target.closest('.neutron-action-menu-content button,.neutron-action-menu-content a')) {
            const menu = event.target.closest('.neutron-action-menu');
            menu.querySelector('summary').focus({preventScroll: true});
            closeMenus();
        }
        const filter = event.target.closest('[data-neutron-filter]');
        if (filter) {
            const wrapper = filter.closest('.dropdown-wrapper');
            wrapper.classList.toggle('force-open');
            filter.setAttribute('aria-expanded', String(wrapper.classList.contains('force-open')));
        }
    }, true);
    document.addEventListener('keydown', event => {
        const menu = event.target.closest('.neutron-action-menu');
        if (!menu) return;
        if (event.key === 'Escape') { menu.open = false; menu.querySelector('summary').focus(); event.preventDefault(); }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            menu.open = true; positionMenu(menu);
            const controls = [...menu.querySelectorAll('.neutron-action-menu-content button,.neutron-action-menu-content a')].filter(el => el.getClientRects().length && !el.disabled);
            if (controls.length) {
                const index = controls.indexOf(document.activeElement);
                controls[(index + (event.key === 'ArrowDown' ? 1 : -1) + controls.length) % controls.length].focus();
            }
            event.preventDefault();
        }
    });
    window.addEventListener('resize', closeMenus);
    document.addEventListener('scroll', event => { if (!event.target.closest?.('.neutron-action-menu-content')) closeMenus(); }, true);
    function updateSelection(root = document) {
        const lists = [...root.querySelectorAll('.hlv-container')];
        if (root.matches?.('.hlv-container')) lists.push(root);
        lists.forEach(list => {
            let selected = list.querySelector('.list-table-row:checked');
            const key = list.dataset.selectedInstancesKey;
            if (key) {
                try { selected ||= JSON.parse(document.getElementById(key)?.dataset.ids || '[]').length > 0; } catch (_) {}
            }
            list.classList.toggle('has-selection', Boolean(selected));
        });
    }
    document.addEventListener('change', event => {
        if (event.target.matches('.list-table-row,.bulk-list-table-row')) updateSelection();
    });
    document.addEventListener('click', event => { if (event.target.closest('.quick-bulk-action')) setTimeout(updateSelection, 0); });
    document.addEventListener('htmx:afterSettle', () => updateSelection());
    document.addEventListener('DOMContentLoaded', () => updateSelection());
    const status = document.querySelector('.neutron-status');
    const message = text => typeof gettext === 'function' ? gettext(text) : text;
    const assets = new Map();
    const loaded = new Set();
    const resolve = url => new URL(url, location.href).href;
    const present = url => Array.from(document.querySelectorAll('script[src], link[rel="stylesheet"]')).some(el => (el.src || el.href) === resolve(url));
    function loadAsset(url) {
        if (assets.has(url)) return assets.get(url);
        if (present(url)) return Promise.resolve();
        const promise = new Promise((done, fail) => {
            const element = document.createElement(url.endsWith('.css') ? 'link' : 'script');
            if (element.tagName === 'LINK') { element.rel = 'stylesheet'; element.href = url; }
            else { element.src = url; element.async = false; }
            element.onload = () => { loaded.add(url); done(); };
            element.onerror = () => { assets.delete(url); element.remove(); fail(new Error('Asset unavailable')); };
            document.head.appendChild(element);
        });
        assets.set(url, promise);
        return promise;
    }
    // Incremented by every main-region navigation; a deferred navigation only runs if it is still the latest.
    let navigationGeneration = 0;
    function assetGroup(url) {
        const path = new URL(url, location.href).pathname;
        return path.includes('/report/') ? 'reports' : path.includes('organisation-chart') ? 'organization' : (path.includes('dashboard') || path === '/ess/') ? 'dashboard' : null;
    }
    function assetsReady(group) {
        // A tag we inserted is ready only once it has loaded; tags from the page HTML already ran.
        return (window.NEUTRON_ASSETS[group] || []).every(url => loaded.has(url) || (!assets.has(url) && present(url)));
    }
    async function loadGroup(group) {
        if (group) for (const asset of window.NEUTRON_ASSETS[group]) await loadAsset(asset);
    }
    window.neutronEnsurePageAssets = async function (url) {
        const generation = ++navigationGeneration;
        await loadGroup(assetGroup(url));
        return generation === navigationGeneration;
    };
    // Any HTMX navigation into the main region (not only the sidebar) waits for the page's
    // feature assets, e.g. module dashboards that need the local ApexCharts build.
    document.addEventListener('htmx:confirm', event => {
        const {question, issueRequest, path, target} = event.detail;
        if (question || !path || !target || !(target.id === 'ohMainContent' || target.closest?.('#ohMainContent'))) return;
        // Swapping the whole region is a navigation and supersedes any deferred one;
        // smaller in-page requests (lazy widgets, filters) leave a pending navigation alone.
        const generation = target.id === 'ohMainContent' ? ++navigationGeneration : navigationGeneration;
        const group = assetGroup(path);
        if (!group || assetsReady(group)) return;
        event.preventDefault();
        loadGroup(group).then(() => {
            if (generation === navigationGeneration) issueRequest(true);
        }, () => {
            // Nothing was requested yet; the failed asset is uncached, so trying again reloads it.
            if (generation !== navigationGeneration) return;
            if (status) status.textContent = message('This page could not load. Check your connection and try again.');
            window.Swal?.fire?.({toast: true, position: 'top-end', icon: 'error', timer: 4000, showConfirmButton: false,
                title: message('This page could not load. Check your connection and try again.')});
        });
    });
    const active = new Map();
    const bar = document.querySelector('.neutron-loading');
    function finish(event) {
        const xhr = event.detail.xhr;
        const target = active.get(xhr);
        active.delete(xhr);
        if (target && !Array.from(active.values()).includes(target)) target.removeAttribute('aria-busy');
        bar?.classList.toggle('active', active.size > 0);
    }
    document.addEventListener('htmx:beforeRequest', event => {
        reflectProfileTab(event.detail.elt.closest('button[data-tab]'));
        const target = event.detail.target;
        active.set(event.detail.xhr, target);
        target?.setAttribute('aria-busy', 'true');
        const modal = target?.closest('.oh-modal');
        const swap = event.detail.elt.closest('[hx-swap]')?.getAttribute('hx-swap') || '';
        if (modal && !/^none(?:\s|$)/.test(swap) && event.detail.elt.closest('[data-toggle="oh-modal-toggle"]')) {
            modal.classList.add('oh-modal--show');
        }
        bar?.classList.add('active');
        if (status) status.textContent = '';
    });
    document.addEventListener('htmx:afterRequest', finish);
    const confirming = new WeakSet();
    document.addEventListener('htmx:confirm', event => {
        const {question, elt, issueRequest} = event.detail;
        if (!question || typeof Swal === 'undefined') return;
        event.preventDefault();
        if (confirming.has(elt)) return;
        confirming.add(elt);
        Swal.fire({
            title: message('Confirm'), text: question, icon: 'question',
            showCancelButton: true,
            confirmButtonText: message('Confirm'), cancelButtonText: message('Cancel'),
            confirmButtonColor: '#051c97', cancelButtonColor: '#494b51',
        }).then(result => {
            if (result.isConfirmed) issueRequest(true);
        }).finally(() => confirming.delete(elt));
    });
    for (const name of ['htmx:timeout', 'htmx:sendError', 'htmx:responseError']) {
        document.addEventListener(name, event => {
            finish(event);
            if (status) status.textContent = message('Unable to load this content. Please try again.');
        });
    }
    document.addEventListener('htmx:sendAbort', finish);

    // Observe only dialog class changes, not every table/chart DOM mutation.
    const observed = new WeakSet();
    const returnFocus = new WeakMap();
    function focusDialog(modal) {
        const focus = modal.querySelector('[autofocus], input:not([type=hidden]):not([disabled]):not(.select2-hidden-accessible), textarea, select:not(.select2-hidden-accessible), button, [href]');
        if (focus && focus.getClientRects().length) focus.focus({preventScroll: true});
        else { modal.tabIndex = -1; modal.focus({preventScroll: true}); }
    }
    const observer = new MutationObserver(records => {
        for (const {target: modal} of records) {
            const open = modal.classList.contains('oh-modal--show');
            modal.setAttribute('aria-hidden', String(!open));
            if (open) {
                if (!returnFocus.has(modal)) returnFocus.set(modal, document.activeElement);
                modal.setAttribute('aria-modal', 'true');
                focusDialog(modal);
            } else {
                modal.removeAttribute('aria-modal');
                const trigger = returnFocus.get(modal);
                if (trigger?.isConnected) trigger.focus({preventScroll: true});
                returnFocus.delete(modal);
            }
        }
    });
    function observe(root) {
        root.querySelectorAll('a[hx-get]:not([href]), li[hx-get]').forEach(control => {
            control.setAttribute('role', 'button');
            control.tabIndex = 0;
        });
        const dialogs = [...root.querySelectorAll('.oh-modal')];
        if (root.matches?.('.oh-modal')) dialogs.push(root);
        dialogs.forEach(modal => {
            if (observed.has(modal)) return;
            observed.add(modal);
            observer.observe(modal, {attributes: true, attributeFilter: ['class']});
            modal.setAttribute('aria-hidden', String(!modal.classList.contains('oh-modal--show')));
        });
    }
    document.addEventListener('click', event => {
        const control = event.target.closest('[data-toggle="oh-modal-toggle"]');
        const action = event.target.closest('a,button,input,select,textarea,summary,details,[role="button"],[hx-get],[hx-post],[hx-delete],[hx-put]');
        if (action && action !== control) return;
        const target = control?.getAttribute('data-target');
        const modal = target ? document.querySelector(target) : null;
        if (modal) {
            if (!modal.classList.contains('oh-modal--show')) returnFocus.set(modal, control);
            // Row actions stop bubbling; capture must open their dialogs too.
            if (!event.target.closest('[hx-confirm]')) modal.classList.add('oh-modal--show');
        }
    }, true);
    observe(document);
    document.addEventListener('htmx:afterSwap', event => {
        observe(event.detail.target);
        const modal = event.detail.target.closest('.oh-modal--show');
        if (modal) focusDialog(modal);
    });
    document.addEventListener('keydown', event => {
        const control = event.target.closest('a[role="button"]:not([href]), li[role="button"]');
        if (control && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            control.click();
            return;
        }
        if (typeof Swal !== 'undefined' && Swal.isVisible()) return;
        const modals = Array.from(document.querySelectorAll('.oh-modal--show')).filter(el => el.getClientRects().length);
        const modal = modals.at(-1);
        if (!modal) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            modal.classList.remove('oh-modal--show');
        } else if (event.key === 'Tab') {
            const items = Array.from(modal.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')).filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);
            const first = items[0], last = items.at(-1);
            if (!first) { event.preventDefault(); return; }
            if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
        }
    });
})();
