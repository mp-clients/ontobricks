/**
 * OntoBricks - settings.js
 * Settings page JavaScript – tabbed layout; global Save persists all sections including Graph DB
 */

document.addEventListener('DOMContentLoaded', function () {

    let currentWarehouseId = null;
    let warehouseLocked = false;

    function escapeHtmlSettings(str) { return escapeHtml(str); }

    loadCurrentConfig();
    loadBaseUri();
    loadCurrentDefaultEmoji();
    loadCloudFetch();
    loadRegistryCacheTtl();
    loadNavbarLogo();

    // =====================================================================
    //  DATABRICKS TAB
    // =====================================================================

    async function loadCurrentConfig() {
        try {
            const response = await fetch('/settings/current', { credentials: 'same-origin' });
            const data = await response.json();

            const tokenBadge = document.getElementById('tokenBadge');
            const authModeDisplay = document.getElementById('authModeDisplay');

            if (data.auth_mode === 'oauth') {
                tokenBadge.className = 'badge bg-success';
                tokenBadge.innerHTML = '<i class="bi bi-shield-check"></i> OAuth configured';
                authModeDisplay.textContent = data.token || '';
                document.getElementById('tokenHelp').textContent = 'Using OAuth Service Principal (Databricks Apps mode)';
            } else if ((data.auth_mode === 'token' || data.auth_mode === 'pat') && data.token) {
                tokenBadge.className = 'badge bg-success';
                tokenBadge.innerHTML = '<i class="bi bi-check-circle"></i> Token configured';
                authModeDisplay.textContent = '';
                document.getElementById('tokenHelp').textContent = data.from_env ? 'From environment variable' : 'From session';
            } else if (data.auth_mode === 'app') {
                tokenBadge.className = 'badge bg-success';
                tokenBadge.innerHTML = '<i class="bi bi-cloud-check"></i> Databricks App';
                authModeDisplay.textContent = '';
                document.getElementById('tokenHelp').textContent = 'Using Databricks Apps authentication';
            } else {
                tokenBadge.className = 'badge bg-danger';
                tokenBadge.innerHTML = '<i class="bi bi-x-circle"></i> Not configured';
                authModeDisplay.textContent = '';
                document.getElementById('tokenHelp').innerHTML = '<i class="bi bi-exclamation-triangle text-warning"></i> Set DATABRICKS_TOKEN or use Databricks Apps';
            }

            currentWarehouseId = data.warehouse_id;
            warehouseLocked = !!data.warehouse_locked;

            if (warehouseLocked) {
                const whSelect = document.getElementById('settingsWarehouseSelect');
                if (whSelect) {
                    whSelect.innerHTML = '<option value="' + escapeHtmlSettings(data.warehouse_id || '') + '" selected>'
                        + escapeHtmlSettings(data.warehouse_id || '(not set)') + '</option>';
                    whSelect.disabled = true;
                }
                const btnRefresh = document.getElementById('btnRefreshWarehouses');
                if (btnRefresh) btnRefresh.disabled = true;
                const whHelp = document.getElementById('warehouseHelp');
                if (whHelp) whHelp.innerHTML = '<i class="bi bi-lock-fill text-muted me-1"></i> Configured via Databricks App resource';
            } else {
                await loadWarehouseSelect(data.warehouse_id);
            }

            const hostDisplay = document.getElementById('currentHostDisplay');
            if (data.host) {
                hostDisplay.innerHTML = '<i class="bi bi-cloud text-success"></i> ' + escapeHtmlSettings(data.host);
            } else {
                hostDisplay.innerHTML = '<i class="bi bi-exclamation-circle text-warning"></i> Not configured';
            }

            if (data.from_env) {
                document.getElementById('envNotice').style.display = 'block';
            }
        } catch (error) {
            console.error('Error loading config:', error);
        }
    }

    async function loadWarehouseSelect(preselectId) {
        const select = document.getElementById('settingsWarehouseSelect');
        if (!select) return;

        try {
            const response = await fetch('/settings/warehouses', { credentials: 'same-origin' });
            const data = await response.json();

            select.innerHTML = '<option value="">-- Select a SQL Warehouse --</option>';

            if (data.warehouses && data.warehouses.length > 0) {
                data.warehouses.forEach(wh => {
                    const stateLabel = wh.state === 'RUNNING' ? ' (running)' : '';
                    const opt = document.createElement('option');
                    opt.value = wh.id;
                    opt.textContent = wh.name + stateLabel;
                    select.appendChild(opt);
                });
            } else if (data.error) {
                select.innerHTML = '<option value="">Error: ' + escapeHtmlSettings(data.error) + '</option>';
            } else {
                select.innerHTML = '<option value="">No warehouses available</option>';
            }

            if (preselectId) {
                select.value = preselectId;
            }
        } catch (error) {
            console.error('Error loading warehouses:', error);
            select.innerHTML = '<option value="">Error loading warehouses</option>';
        }
    }

    document.getElementById('btnRefreshWarehouses')?.addEventListener('click', () => loadWarehouseSelect(currentWarehouseId));

    document.getElementById('btnTestConnection')?.addEventListener('click', async function () {
        const whId = document.getElementById('settingsWarehouseSelect').value || currentWarehouseId;
        const resultDiv = document.getElementById('connectionResult');

        if (!whId) {
            showNotification('Please select a SQL Warehouse first', 'warning');
            return;
        }

        resultDiv.style.display = 'block';
        resultDiv.innerHTML = '<div class="alert alert-info"><i class="bi bi-hourglass-split"></i> Testing connection...</div>';

        try {
            const response = await fetch('/settings/test-connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ warehouse_id: whId })
            });
            const result = await response.json();

            if (result.success) {
                resultDiv.innerHTML = `<div class="alert alert-success"><i class="bi bi-check-circle"></i> ${result.message}</div>`;
            } else {
                resultDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> ${result.message}</div>`;
            }
        } catch (error) {
            resultDiv.innerHTML = `<div class="alert alert-danger"><i class="bi bi-x-circle"></i> Error: ${error.message}</div>`;
        }
    });

    // =====================================================================
    //  GLOBAL TAB – Base URI
    // =====================================================================

    async function loadBaseUri() {
        try {
            const response = await fetch('/settings/get-base-uri', { credentials: 'same-origin' });
            const result = await response.json();
            if (result.success && result.base_uri) {
                document.getElementById('baseUriDefault').value = result.base_uri;
            }
        } catch (error) {
            console.log('Using default base URI');
        }
    }

    // =====================================================================
    //  GLOBAL TAB – Registry Cache TTL
    // =====================================================================

    async function loadRegistryCacheTtl() {
        try {
            const resp = await fetch('/settings/get-registry-cache-ttl', { credentials: 'same-origin' });
            const result = await resp.json();
            if (result.success && result.registry_cache_ttl != null) {
                document.getElementById('registryCacheTtl').value = result.registry_cache_ttl;
            }
        } catch (error) {
            console.log('Using default registry cache TTL');
        }
    }

    async function loadCloudFetch() {
        try {
            const resp = await fetch('/settings/get-cloud-fetch', { credentials: 'same-origin' });
            const result = await resp.json();
            const toggle = document.getElementById('cloudFetchEnabled');
            if (toggle && result.success && typeof result.use_cloud_fetch === 'boolean') {
                toggle.checked = result.use_cloud_fetch;
            }
        } catch (error) {
            console.log('Using default CloudFetch setting');
        }
    }

    // =====================================================================
    //  GLOBAL TAB – Default Emoji Picker (uses shared EmojiPicker module)
    // =====================================================================

    async function loadCurrentDefaultEmoji() {
        try {
            const response = await fetch('/settings/get-default-emoji', { credentials: 'same-origin' });
            const result = await response.json();
            if (result.success && result.emoji) {
                document.getElementById('currentDefaultEmoji').textContent = result.emoji;
            }
        } catch (error) {
            console.log('Using default emoji');
        }
    }

    async function selectDefaultEmoji(emoji) {
        try {
            const response = await fetch('/settings/set-default-emoji', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ emoji })
            });
            const result = await response.json();
            if (result.success) {
                document.getElementById('currentDefaultEmoji').textContent = emoji;
                showNotification('Default class icon updated to ' + emoji, 'success', 2000);
            } else {
                showNotification('Error: ' + result.message, 'error');
            }
        } catch (error) {
            showNotification('Error saving default emoji: ' + error.message, 'error');
        }
    }

    const changeBtn = document.getElementById('changeDefaultEmoji');
    if (changeBtn) {
        EmojiPicker.create({
            triggerEl:   changeBtn,
            previewEl:   document.getElementById('currentDefaultEmoji'),
            containerEl: document.getElementById('defaultEmojiPickerMount'),
            showSearch:  false,
            onSelect:    function (emoji) { selectDefaultEmoji(emoji); }
        });
    }

    // =====================================================================
    //  GLOBAL TAB – Application Logo (top-bar branding)
    // =====================================================================

    async function loadNavbarLogo() {
        try {
            const resp = await fetch('/settings/navbar-logo', { credentials: 'same-origin' });
            const result = await resp.json();
            if (!result.success) return;
            const previewEl = document.getElementById('navbarLogoPreview');
            if (previewEl && result.logo_url) previewEl.src = result.logo_url;
            const statusEl = document.getElementById('navbarLogoStatus');
            if (statusEl) {
                statusEl.textContent = result.is_custom ? 'Custom logo active' : 'Using default logo';
            }
        } catch (e) {
            console.log('Could not load navbar logo settings');
        }
    }

    const logoFileInput = document.getElementById('navbarLogoFile');
    const logoUploadBtn = document.getElementById('btnUploadNavbarLogo');
    const logoResetBtn  = document.getElementById('btnResetNavbarLogo');
    const logoPreviewEl = document.getElementById('navbarLogoPreview');
    const logoStatusEl  = document.getElementById('navbarLogoStatus');

    if (logoFileInput) {
        logoFileInput.addEventListener('change', () => {
            const file = logoFileInput.files && logoFileInput.files[0];
            if (logoUploadBtn) logoUploadBtn.disabled = !file;
            if (file && logoPreviewEl) {
                const reader = new FileReader();
                reader.onload = (ev) => { logoPreviewEl.src = ev.target.result; };
                reader.readAsDataURL(file);
            }
        });
    }

    if (logoUploadBtn) {
        logoUploadBtn.addEventListener('click', async () => {
            const file = logoFileInput && logoFileInput.files && logoFileInput.files[0];
            if (!file) return;
            const MAX = 1024 * 1024;
            if (file.size > MAX) {
                showNotification(`Image too large (${file.size} bytes); max ${MAX} bytes`, 'error');
                return;
            }
            logoUploadBtn.disabled = true;
            const original = logoUploadBtn.innerHTML;
            logoUploadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Uploading...';
            try {
                const fd = new FormData();
                fd.append('file', file);
                const resp = await fetch('/settings/navbar-logo', {
                    method: 'POST',
                    body: fd,
                    credentials: 'same-origin'
                });
                const result = await resp.json();
                if (result.success) {
                    if (logoPreviewEl && result.logo_url) logoPreviewEl.src = result.logo_url;
                    if (logoStatusEl) logoStatusEl.textContent = 'Custom logo active';
                    if (logoFileInput) logoFileInput.value = '';
                    if (typeof fetchCachedInvalidate === 'function') {
                        fetchCachedInvalidate('/navbar/state');
                    }
                    const navImg = document.getElementById('brandLogoImg');
                    if (navImg && result.logo_url) navImg.src = result.logo_url;
                    showNotification('Application logo updated', 'success', 2500);
                } else {
                    showNotification('Error: ' + (result.message || 'upload failed'), 'error');
                }
            } catch (e) {
                showNotification('Error uploading logo: ' + e.message, 'error');
            } finally {
                logoUploadBtn.innerHTML = original;
                logoUploadBtn.disabled = !(logoFileInput && logoFileInput.files && logoFileInput.files[0]);
            }
        });
    }

    if (logoResetBtn) {
        logoResetBtn.addEventListener('click', async () => {
            const confirmed = await (typeof showConfirmDialog === 'function'
                ? showConfirmDialog({
                    title: 'Reset application logo',
                    message: 'Restore the default OntoBricks logo for all users?',
                    confirmText: 'Reset',
                    confirmClass: 'btn-warning',
                    icon: 'arrow-counterclockwise'
                })
                : Promise.resolve(window.confirm('Restore the default logo?')));
            if (!confirmed) return;
            logoResetBtn.disabled = true;
            try {
                const resp = await fetch('/settings/navbar-logo', {
                    method: 'DELETE',
                    credentials: 'same-origin'
                });
                const result = await resp.json();
                if (result.success) {
                    if (logoPreviewEl && result.logo_url) logoPreviewEl.src = result.logo_url;
                    if (logoStatusEl) logoStatusEl.textContent = 'Using default logo';
                    if (logoFileInput) logoFileInput.value = '';
                    if (logoUploadBtn) logoUploadBtn.disabled = true;
                    if (typeof fetchCachedInvalidate === 'function') {
                        fetchCachedInvalidate('/navbar/state');
                    }
                    const navImg = document.getElementById('brandLogoImg');
                    if (navImg && result.logo_url) navImg.src = result.logo_url;
                    showNotification('Application logo reset to default', 'success', 2500);
                } else {
                    showNotification('Error: ' + (result.message || 'reset failed'), 'error');
                }
            } catch (e) {
                showNotification('Error resetting logo: ' + e.message, 'error');
            } finally {
                logoResetBtn.disabled = false;
            }
        });
    }

    // =====================================================================
    //  LADYBUGDB TAB – Graph Engine selector
    // =====================================================================

    /** Show Lakebase picker vs Ladybug local-files section from graph engine select. */
    function applyGraphDbEnginePanels() {
        const sel = document.getElementById('graphEngineSelect');
        const lakePanel = document.getElementById('lakebaseGraphPanel');
        const ladybugFilesWrap = document.getElementById('ladybugLocalFilesWrap');
        if (!sel) return;
        const eng = sel.value;
        if (lakePanel) {
            lakePanel.style.display = eng === 'lakebase' ? 'block' : 'none';
        }
        if (ladybugFilesWrap) {
            ladybugFilesWrap.style.display = eng === 'ladybug' ? '' : 'none';
        }
    }

    async function loadLakebaseGraphDatabasesForGraphEngine() {
        const sel = document.getElementById('lakebaseGraphDb');
        const help = document.getElementById('lakebaseGraphDbHelp');
        const ta = document.getElementById('graphEngineConfig');
        if (!sel) return;
        sel.disabled = true;
        sel.innerHTML = '<option value="">Loading databases…</option>';
        let cfgDb = '';
        try {
            const o = JSON.parse(ta?.value || '{}');
            if (o && typeof o.database === 'string') cfgDb = o.database;
        } catch (_) { /* ignore */ }
        try {
            const resp = await fetch('/settings/registry/lakebase-databases', { credentials: 'same-origin' });
            const data = await resp.json();
            if (!data.success) {
                sel.innerHTML = '<option value="">(default — use bound database)</option>';
                if (help) help.innerHTML = '<i class="bi bi-exclamation-triangle text-warning me-1"></i>'
                    + escapeHtmlSettings(data.message || 'Could not list databases.');
                if (cfgDb) {
                    const opt = document.createElement('option');
                    opt.value = cfgDb;
                    opt.textContent = cfgDb + ' (configured)';
                    opt.selected = true;
                    sel.appendChild(opt);
                }
                sel.disabled = false;
                return;
            }
            const bound = data.bound_database || '';
            const dbs = Array.isArray(data.databases) ? data.databases : [];
            sel.innerHTML = '';
            const defOpt = document.createElement('option');
            defOpt.value = '';
            defOpt.textContent = '(default — bound database' + (bound ? ': ' + bound : '') + ')';
            sel.appendChild(defOpt);
            for (const db of dbs) {
                const opt = document.createElement('option');
                opt.value = db.name;
                let label = db.name;
                if (db.is_bound) label += ' (bound)';
                if (!db.connectable) label += ' — no CONNECT';
                opt.textContent = label;
                if (!db.connectable) opt.disabled = true;
                if (db.name === cfgDb) opt.selected = true;
                sel.appendChild(opt);
            }
            if (!cfgDb) defOpt.selected = true;
            sel.disabled = false;
            if (help) help.innerHTML = 'Same discovery API as Registry → Lakebase database picker.';
        } catch (e) {
            sel.innerHTML = '<option value="">(default)</option>';
            sel.disabled = false;
            if (help) help.innerHTML = '<i class="bi bi-x-circle text-danger me-1"></i>'
                + escapeHtmlSettings(e.message || 'Network error');
        }
    }

    /** Merge Lakebase form fields + optional managed-sync options into the JSON textarea. */
    function mergeLakebasePanelIntoConfigTextarea() {
        const ta = document.getElementById('graphEngineConfig');
        const dbSel = document.getElementById('lakebaseGraphDb');
        const schIn = document.getElementById('lakebaseGraphSchema');
        const syncModeEl = document.getElementById('lakebaseSyncMode');
        if (!ta || !dbSel || !schIn) return;
        let o = {};
        try { o = JSON.parse(ta.value || '{}'); } catch (_) { o = {}; }
        if (typeof o !== 'object' || Array.isArray(o)) o = {};
        o.database = dbSel.value || '';
        o.schema = (schIn.value || 'ontobricks_graph').trim() || 'ontobricks_graph';
        const mode = (syncModeEl && syncModeEl.value === 'managed_synced') ? 'managed_synced' : 'app_managed';
        if (mode === 'managed_synced') {
            o.sync_mode = 'managed_synced';
            const stEl = document.getElementById('lakebaseSyncTableMode');
            const toutEl = document.getElementById('lakebaseSyncTimeout');
            const ucEl = document.getElementById('lakebaseUcCatalog');
            if (stEl) o.sync_table_mode = stEl.value || 'snapshot';
            if (toutEl) {
                var n = parseInt(toutEl.value, 10);
                o.sync_timeout_s = (!isNaN(n) && n > 0) ? n : 600;
            }
            if (ucEl) {
                var cat = (ucEl.value || '').trim();
                if (cat) o.sync_uc_catalog = cat;
                else delete o.sync_uc_catalog;
            }
        } else {
            o.sync_mode = 'app_managed';
            delete o.sync_table_mode;
            delete o.sync_timeout_s;
            delete o.sync_uc_catalog;
        }
        ta.value = JSON.stringify(o, null, 2);
    }

    function toggleLakebaseManagedSyncPanel() {
        const sm = document.getElementById('lakebaseSyncMode');
        const panel = document.getElementById('lakebaseManagedSyncPanel');
        if (!sm || !panel) return;
        panel.classList.toggle('d-none', sm.value !== 'managed_synced');
    }

    function updateLakebaseSyncModeHelp() {
        const sm = document.getElementById('lakebaseSyncMode');
        const v = sm && sm.value === 'managed_synced' ? 'managed_synced' : 'app_managed';
        document.querySelectorAll('[data-lk-mode]').forEach(function (el) {
            el.classList.toggle('d-none', el.getAttribute('data-lk-mode') !== v);
        });
    }

    async function loadUcCatalogsForGraphEngine() {
        const dl = document.getElementById('lakebaseUcCatalogDatalist');
        const msg = document.getElementById('lakebaseUcCatalogLoadMsg');
        const btn = document.getElementById('btnLoadUcCatalogs');
        if (!dl) return;
        if (msg) {
            msg.classList.remove('d-none');
            msg.className = 'form-text small mt-1 text-muted';
            msg.textContent = 'Loading catalogs…';
        }
        if (btn) btn.disabled = true;
        try {
            const resp = await fetch('/settings/graph-engine/uc-catalogs', { credentials: 'same-origin' });
            const data = resp.ok ? await resp.json() : {};
            dl.innerHTML = '';
            if (data.success && Array.isArray(data.catalogs)) {
                data.catalogs.forEach(function (name) {
                    const opt = document.createElement('option');
                    opt.value = name;
                    dl.appendChild(opt);
                });
                if (msg) {
                    msg.className = 'form-text small mt-1 text-success';
                    msg.textContent = 'Loaded ' + data.catalogs.length + ' catalog(s). Type or pick a value above.';
                }
            } else {
                if (msg) {
                    msg.className = 'form-text small mt-1 text-warning';
                    msg.textContent = data.message || 'Could not list catalogs — type the catalog name manually.';
                }
            }
        } catch (e) {
            if (msg) {
                msg.className = 'form-text small mt-1 text-warning';
                msg.textContent = e.message || 'Network error';
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    function applyLakebaseFormFromConfigTextarea() {
        const ta = document.getElementById('graphEngineConfig');
        const schIn = document.getElementById('lakebaseGraphSchema');
        const syncModeEl = document.getElementById('lakebaseSyncMode');
        if (!ta || !schIn) return;
        try {
            const o = JSON.parse(ta.value || '{}');
            if (o && typeof o.schema === 'string' && o.schema.trim()) {
                schIn.value = o.schema.trim();
            }
            if (syncModeEl) {
                syncModeEl.value = (o.sync_mode === 'managed_synced') ? 'managed_synced' : 'app_managed';
            }
            const stEl = document.getElementById('lakebaseSyncTableMode');
            if (stEl && o.sync_table_mode && typeof o.sync_table_mode === 'string') {
                stEl.value = o.sync_table_mode;
            }
            const toutEl = document.getElementById('lakebaseSyncTimeout');
            if (toutEl && o.sync_timeout_s != null) {
                toutEl.value = String(parseInt(o.sync_timeout_s, 10) || 600);
            }
            const ucEl = document.getElementById('lakebaseUcCatalog');
            if (ucEl && o.sync_uc_catalog != null) {
                ucEl.value = String(o.sync_uc_catalog);
            } else if (ucEl) {
                ucEl.value = '';
            }
        } catch (_) { /* ignore */ }
        toggleLakebaseManagedSyncPanel();
        updateLakebaseSyncModeHelp();
    }

    async function loadLakebaseGraphHealth() {
        const msgEl = document.getElementById('lakebaseGraphHealthMessage');
        const dl = document.getElementById('lakebaseGraphHealthDl');
        const btn = document.getElementById('btnRefreshLakebaseGraphHealth');
        const engSel = document.getElementById('graphEngineSelect');
        if (!msgEl || !dl || engSel?.value !== 'lakebase') return;

        if (btn) btn.disabled = true;
        dl.innerHTML = '';
        msgEl.style.display = '';
        msgEl.className = 'small mb-2 text-muted';
        msgEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Checking Lakebase…';

        function row(label, value) {
            return '<dt class="col-sm-4 text-muted">' + escapeHtmlSettings(label) + '</dt>'
                + '<dd class="col-sm-8 font-monospace text-break">' + value + '</dd>';
        }

        try {
            const resp = await fetch('/settings/graph-engine/lakebase-health', { credentials: 'same-origin' });
            const data = resp.ok ? await resp.json() : {};
            if (!data.success) {
                msgEl.className = 'small mb-2 text-warning';
                const m = data.message || data.reason || 'Health check failed';
                msgEl.innerHTML = '<i class="bi bi-exclamation-triangle me-1"></i>' + escapeHtmlSettings(m);
                if (data.host) {
                    dl.innerHTML = row('PGHOST', escapeHtmlSettings(String(data.host)));
                }
                return;
            }
            msgEl.className = 'small mb-2 ' + (data.schema_exists ? 'text-success' : 'text-warning');
            msgEl.innerHTML = '<i class="bi bi-' + (data.schema_exists ? 'check-circle' : 'exclamation-triangle') + ' me-1"></i>'
                + escapeHtmlSettings(data.message || 'OK');
            dl.innerHTML = (
                row('PGHOST', escapeHtmlSettings(String(data.host || '')))
                + row('Port', escapeHtmlSettings(String(data.port != null ? data.port : '')))
                + row('Bound PGDATABASE', escapeHtmlSettings(String(data.bound_database || '')))
                + row('Effective database', escapeHtmlSettings(String(data.effective_database || '')))
                + row('Graph schema', escapeHtmlSettings(String(data.graph_schema || '')))
                + row('Schema exists', data.schema_exists ? 'yes' : 'no')
                + row('Tables in schema', escapeHtmlSettings(String(data.tables_in_schema != null ? data.tables_in_schema : '')))
            );
        } catch (e) {
            msgEl.className = 'small mb-2 text-danger';
            msgEl.innerHTML = '<i class="bi bi-x-circle me-1"></i>' + escapeHtmlSettings(e.message || 'Network error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    let ladybugFilesLoaded = false;

    function setGraphDbTabLoading(loading) {
        const banner = document.getElementById('graphDbTabLoadingBanner');
        if (!banner) return;
        banner.classList.toggle('d-none', !loading);
        banner.classList.toggle('d-flex', loading);
    }

    /** Reload engine + JSON from server so the tab matches persisted settings after every visit. */
    async function refreshGraphDbTabFromServer() {
        const sel = document.getElementById('graphEngineSelect');
        const ta = document.getElementById('graphEngineConfig');
        if (!sel || !ta) return;
        try {
            const [engResp, cfgResp] = await Promise.all([
                fetch('/settings/graph-engine', { credentials: 'same-origin' }),
                fetch('/settings/graph-engine-config', { credentials: 'same-origin' }),
            ]);
            const engData = engResp.ok ? await engResp.json() : {};
            const cfgData = cfgResp.ok ? await cfgResp.json() : {};
            if (cfgData.success) {
                ta.value = JSON.stringify(cfgData.graph_engine_config || {}, null, 2);
            }
            const rawEng = engData.graph_engine;
            if (engData.success && rawEng && typeof rawEng === 'string') {
                var allowed = Array.isArray(engData.allowed_engines) ? engData.allowed_engines : [];
                if (allowed.length === 0 && (rawEng === 'ladybug' || rawEng === 'lakebase')) {
                    sel.value = rawEng;
                } else if (allowed.indexOf(rawEng) >= 0) {
                    sel.value = rawEng;
                } else {
                    sel.value = 'ladybug';
                }
            }
            applyLakebaseFormFromConfigTextarea();
            if (sel.value === 'lakebase') {
                await loadLakebaseGraphDatabasesForGraphEngine();
                await loadLakebaseGraphHealth();
            }
        } catch (e) {
            console.log('Graph DB tab refresh failed', e);
        } finally {
            applyGraphDbEnginePanels();
        }
    }

    document.getElementById('graphEngineSelect')?.addEventListener('change', async function () {
        applyGraphDbEnginePanels();
        if (this.value === 'lakebase') {
            applyLakebaseFormFromConfigTextarea();
            await loadLakebaseGraphDatabasesForGraphEngine();
            await loadLakebaseGraphHealth();
        } else if (this.value === 'ladybug' && !ladybugFilesLoaded) {
            loadLadybugFiles();
        }
    });

    document.getElementById('lakebaseGraphDb')?.addEventListener('change', mergeLakebasePanelIntoConfigTextarea);
    document.getElementById('lakebaseGraphSchema')?.addEventListener('input', mergeLakebasePanelIntoConfigTextarea);
    document.getElementById('lakebaseGraphSchema')?.addEventListener('change', mergeLakebasePanelIntoConfigTextarea);
    document.getElementById('lakebaseSyncMode')?.addEventListener('change', function () {
        toggleLakebaseManagedSyncPanel();
        updateLakebaseSyncModeHelp();
        mergeLakebasePanelIntoConfigTextarea();
    });
    document.getElementById('lakebaseSyncTableMode')?.addEventListener('change', mergeLakebasePanelIntoConfigTextarea);
    document.getElementById('lakebaseSyncTimeout')?.addEventListener('input', mergeLakebasePanelIntoConfigTextarea);
    document.getElementById('lakebaseSyncTimeout')?.addEventListener('change', mergeLakebasePanelIntoConfigTextarea);
    document.getElementById('lakebaseUcCatalog')?.addEventListener('input', mergeLakebasePanelIntoConfigTextarea);
    document.getElementById('lakebaseUcCatalog')?.addEventListener('change', mergeLakebasePanelIntoConfigTextarea);
    document.getElementById('btnLoadUcCatalogs')?.addEventListener('click', () => loadUcCatalogsForGraphEngine());

    document.getElementById('btnRefreshLakebaseGraphHealth')?.addEventListener('click', () => loadLakebaseGraphHealth());

    /** Persist graph engine and JSON config (used by global Save). */
    async function saveGraphDbSettings(errors) {
        const sel = document.getElementById('graphEngineSelect');
        const ta = document.getElementById('graphEngineConfig');
        const errDiv = document.getElementById('graphEngineConfigError');
        if (!sel || !ta) return;

        if (errDiv) errDiv.style.display = 'none';

        try {
            const resp = await fetch('/settings/graph-engine', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ graph_engine: sel.value }),
            });
            const result = await resp.json();
            if (!result.success) {
                errors.push('Graph DB engine: ' + (result.message || 'Unknown error'));
                return;
            }

            if (sel.value === 'lakebase') {
                mergeLakebasePanelIntoConfigTextarea();
            }

            let parsed;
            try {
                parsed = JSON.parse(ta.value || '{}');
            } catch (parseErr) {
                errors.push('Graph DB config: invalid JSON (' + parseErr.message + ')');
                if (errDiv) {
                    errDiv.textContent = 'Invalid JSON: ' + parseErr.message;
                    errDiv.style.display = 'block';
                }
                return;
            }
            if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
                errors.push('Graph DB config: must be a JSON object');
                if (errDiv) {
                    errDiv.textContent = 'Configuration must be a JSON object (not an array or primitive)';
                    errDiv.style.display = 'block';
                }
                return;
            }

            const cfgResp = await fetch('/settings/graph-engine-config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ graph_engine_config: parsed }),
            });
            const cfgJson = await cfgResp.json();
            if (!cfgJson.success) {
                errors.push('Graph DB config: ' + (cfgJson.message || 'Unknown error'));
                return;
            }
            ta.value = JSON.stringify(cfgJson.graph_engine_config || parsed, null, 2);
            applyGraphDbEnginePanels();
            if (sel.value === 'ladybug' && !ladybugFilesLoaded) loadLadybugFiles();
            if (sel.value === 'lakebase') loadLakebaseGraphHealth();
        } catch (e) {
            errors.push('Graph DB: ' + e.message);
        }
    }

    // =====================================================================
    //  LADYBUGDB TAB – Local files
    // =====================================================================

    document.getElementById('tab-ladybugdb')?.addEventListener('shown.bs.tab', async () => {
        setGraphDbTabLoading(true);
        try {
            await refreshGraphDbTabFromServer();
            const sel = document.getElementById('graphEngineSelect');
            if (sel && sel.value === 'ladybug' && !ladybugFilesLoaded) {
                await loadLadybugFiles();
            }
        } finally {
            setGraphDbTabLoading(false);
        }
    });

    document.getElementById('btnRefreshLadybugFiles')?.addEventListener('click', () => loadLadybugFiles());

    async function loadLadybugFiles() {
        const container = document.getElementById('ladybugFilesContainer');
        if (!container) return;

        container.innerHTML = '<div class="text-center text-muted small py-4">' +
            '<span class="spinner-border spinner-border-sm me-1"></span> Loading files...</div>';

        try {
            const resp = await fetch('/settings/ladybugdb/files', { credentials: 'same-origin' });
            const data = await resp.json();

            if (!data.success) {
                container.innerHTML = '<div class="text-muted small py-3">' +
                    '<i class="bi bi-exclamation-triangle text-warning me-1"></i> ' +
                    escapeHtmlSettings(data.message || 'Could not list files') + '</div>';
                return;
            }

            if (!data.files || data.files.length === 0) {
                container.innerHTML = '<div class="text-muted small py-3 text-center">' +
                    '<i class="bi bi-folder"></i> No files in <code>' +
                    escapeHtmlSettings(data.base_dir) + '</code></div>';
                ladybugFilesLoaded = true;
                return;
            }

            let html = '<div class="table-responsive">' +
                '<table class="table table-sm table-hover align-middle mb-0">' +
                '<thead><tr>' +
                    '<th class="ps-3">Name</th>' +
                    '<th class="text-end" style="width:7rem;">Size</th>' +
                    '<th class="text-end" style="width:13rem;">Last Modified</th>' +
                    '<th class="text-end pe-3" style="width:3rem;"></th>' +
                '</tr></thead><tbody>';

            data.files.forEach(f => {
                const icon = f.is_dir
                    ? '<i class="bi bi-folder-fill text-warning me-1"></i>'
                    : '<i class="bi bi-file-earmark me-1 text-secondary"></i>';
                const deleteBtn = '<button type="button" class="btn btn-sm btn-outline-danger border-0 ladybug-delete-btn" ' +
                    'data-name="' + escapeHtmlSettings(f.name) + '" title="Delete ' + escapeHtmlSettings(f.name) + '">' +
                    '<i class="bi bi-trash"></i></button>';
                html += '<tr>' +
                    '<td class="ps-3 font-monospace">' + icon + escapeHtmlSettings(f.name) + '</td>' +
                    '<td class="text-end text-muted small">' + escapeHtmlSettings(f.size_display) + '</td>' +
                    '<td class="text-end text-muted small">' + escapeHtmlSettings(f.modified_display) + '</td>' +
                    '<td class="text-end pe-3">' + deleteBtn + '</td>' +
                '</tr>';
            });

            html += '</tbody></table></div>';
            container.innerHTML = html;
            ladybugFilesLoaded = true;

            container.querySelectorAll('.ladybug-delete-btn').forEach(btn => {
                btn.addEventListener('click', () => deleteLadybugFile(btn.dataset.name));
            });
        } catch (e) {
            console.error('Error loading Graph DB files:', e);
            container.innerHTML = '<div class="text-danger small py-3">' +
                '<i class="bi bi-x-circle me-1"></i> Error loading files: ' +
                escapeHtmlSettings(e.message) + '</div>';
        }
    }

    async function deleteLadybugFile(name) {
        const confirmed = await showConfirmDialog({
            title: 'Delete Graph File',
            message: 'Delete "' + name + '" from local storage? This cannot be undone.',
            confirmText: 'Delete',
            confirmClass: 'btn-danger',
            icon: 'trash'
        });
        if (!confirmed) return;

        try {
            const resp = await fetch('/settings/ladybugdb/files/' + encodeURIComponent(name), {
                method: 'DELETE',
                credentials: 'same-origin'
            });
            const data = await resp.json();
            if (data.success) {
                showNotification(data.message, 'success', 2000);
                await loadLadybugFiles();
            } else {
                showNotification('Error: ' + data.message, 'error');
            }
        } catch (e) {
            showNotification('Error deleting file: ' + e.message, 'error');
        }
    }

    // =====================================================================
    //  GLOBAL SAVE BUTTON – warehouse, global prefs, CloudFetch, Graph DB
    // =====================================================================

    document.getElementById('btnSaveAllSettings')?.addEventListener('click', async function () {
        const btn = this;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving...';

        const errors = [];

        // 1. Save warehouse (skip when locked by Databricks App resource)
        const whId = document.getElementById('settingsWarehouseSelect').value;
        if (whId && !warehouseLocked) {
            try {
                const resp = await fetch('/settings/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ warehouse_id: whId })
                });
                const r = await resp.json();
                if (r.success) currentWarehouseId = whId;
                else errors.push('Warehouse: ' + r.message);
            } catch (e) { errors.push('Warehouse: ' + e.message); }
        }

        // 2. Save base URI
        const baseUri = document.getElementById('baseUriDefault').value.trim();
        if (baseUri) {
            try {
                const resp = await fetch('/settings/save-base-uri', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ base_uri: baseUri })
                });
                const r = await resp.json();
                if (!r.success) errors.push('Base URI: ' + r.message);
            } catch (e) { errors.push('Base URI: ' + e.message); }
        }

        // 3. Save registry cache TTL
        const ttlInput = document.getElementById('registryCacheTtl');
        if (ttlInput) {
            const ttl = parseInt(ttlInput.value, 10);
            if (!isNaN(ttl) && ttl >= 10) {
                try {
                    const resp = await fetch('/settings/save-registry-cache-ttl', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({ registry_cache_ttl: ttl })
                    });
                    const r = await resp.json();
                    if (!r.success) errors.push('Cache TTL: ' + r.message);
                } catch (e) { errors.push('Cache TTL: ' + e.message); }
            }
        }

        // 4. Save CloudFetch toggle
        const cloudFetchToggle = document.getElementById('cloudFetchEnabled');
        if (cloudFetchToggle) {
            try {
                const resp = await fetch('/settings/save-cloud-fetch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ use_cloud_fetch: !!cloudFetchToggle.checked })
                });
                const r = await resp.json();
                if (!r.success) errors.push('CloudFetch: ' + r.message);
            } catch (e) { errors.push('CloudFetch: ' + e.message); }
        }

        // 5. Graph DB engine + JSON config (same tab; top Save only)
        await saveGraphDbSettings(errors);

        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-check-circle me-1"></i> Save';

        if (errors.length > 0) {
            showNotification('Some settings failed to save:\n' + errors.join('\n'), 'error');
        } else {
            showNotification('All settings saved', 'success', 2000);
        }
    });
});
