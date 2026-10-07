(() => {
    const {el, readBootstrap, createAlert, createRequester, createActionRunner, plural} = window.HostAIAdmin;
    const bootstrap = readBootstrap("diningAdminBootstrap");
    if (!bootstrap) {
        return;
    }

    const state = {
        restaurantId: bootstrap.restaurantId,
        zones: bootstrap.zones || [],
        tables: bootstrap.tables || [],
        editingTableId: null,
        tableDialogMode: "single",
        qrTableId: null,
        submitting: false,
    };

    const $ = (id) => document.getElementById(id);
    const basePath = `/api/dining/${state.restaurantId}`;

    const zoneList = $("zoneList");
    const zoneCreateForm = $("zoneCreateForm");
    const tableGroups = $("tableGroups");
    const tableSummary = $("tableSummary");
    const tableDialog = $("tableDialog");
    const tableForm = $("tableForm");
    const tableFormError = $("tableFormError");
    const tableDialogTitle = $("tableDialogTitle");
    const tableSubmitButton = $("tableSubmitButton");
    const qrDialog = $("qrDialog");
    const qrDialogTitle = $("qrDialogTitle");
    const qrDialogError = $("qrDialogError");
    const qrImage = $("qrImage");

    const showAlert = createAlert($("menuAdminAlert"));
    const request = createRequester(basePath);

    async function reload() {
        const data = await request("/setup");
        state.zones = data.zones;
        state.tables = data.tables;
        render();
    }

    const runAction = createActionRunner({reload, showAlert});

    const zoneById = (zoneId) => state.zones.find((zone) => zone.id === zoneId);
    const tableById = (tableId) => state.tables.find((table) => table.id === tableId);

    // --- Zones ------------------------------------------------------------

    function renderZones() {
        zoneList.replaceChildren();
        if (!state.zones.length) {
            zoneList.append(el("li", {
                className: "empty-state",
                text: "Sin zonas todavía. Son opcionales, pero ayudan al camarero en locales grandes.",
            }));
            return;
        }

        state.zones.forEach((zone, index) => {
            const tableCount = state.tables.filter((table) => table.zone_id === zone.id && table.is_active).length;
            zoneList.append(el("li", {
                className: `category-row${zone.is_active ? "" : " is-inactive"}`,
                attrs: {"data-zone-row": zone.id},
            }, [
                el("div", {className: "category-copy"}, [
                    el("span", {className: "category-name", text: zone.name}),
                    el("span", {className: "category-count", text: plural(tableCount, "mesa", "mesas")}),
                    zone.is_active ? null : el("span", {className: "dish-hidden-badge", text: "Inactiva"}),
                ]),
                el("div", {className: "row-actions"}, [
                    el("button", {
                        className: "icon-action",
                        text: "↑",
                        attrs: {type: "button", "aria-label": `Subir ${zone.name}`, disabled: index === 0, "data-move": "up", "data-id": zone.id},
                    }),
                    el("button", {
                        className: "icon-action",
                        text: "↓",
                        attrs: {type: "button", "aria-label": `Bajar ${zone.name}`, disabled: index === state.zones.length - 1, "data-move": "down", "data-id": zone.id},
                    }),
                    el("button", {
                        className: "menu-admin-button is-small",
                        text: "Renombrar",
                        attrs: {type: "button", "data-rename": zone.id},
                    }),
                    el("button", {
                        className: "menu-admin-button is-small",
                        text: zone.is_active ? "Desactivar" : "Activar",
                        attrs: {type: "button", "data-toggle-zone": zone.id},
                    }),
                ]),
            ]));
        });
    }

    function startRename(zoneId) {
        const row = zoneList.querySelector(`[data-zone-row="${zoneId}"]`);
        const zone = zoneById(zoneId);
        if (!row || !zone) {
            return;
        }
        const input = el("input", {attrs: {type: "text", maxlength: 120, "aria-label": "Nuevo nombre"}});
        input.value = zone.name;
        const form = el("form", {className: "inline-form rename-form"}, [
            input,
            el("button", {className: "menu-admin-button is-small is-primary", text: "Guardar", attrs: {type: "submit"}}),
            el("button", {className: "menu-admin-button is-small", text: "Cancelar", attrs: {type: "button", "data-cancel-rename": ""}}),
        ]);
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const name = input.value.trim();
            if (!name || name === zone.name) {
                renderZones();
                return;
            }
            runAction(
                () => request(`/zones/${zoneId}`, {method: "PATCH", body: JSON.stringify({name})}),
                "Zona renombrada.",
            );
        });
        row.replaceChildren(form);
        input.focus();
        input.select();
    }

    async function moveZone(zoneId, direction) {
        const ordered = [...state.zones];
        const index = ordered.findIndex((zone) => zone.id === zoneId);
        const target = direction === "up" ? index - 1 : index + 1;
        if (index < 0 || target < 0 || target >= ordered.length) {
            return;
        }
        [ordered[index], ordered[target]] = [ordered[target], ordered[index]];
        const updates = ordered
            .map((zone, position) => ({zone, display_order: position * 10}))
            .filter(({zone, display_order}) => zone.display_order !== display_order);
        await runAction(async () => {
            for (const {zone, display_order} of updates) {
                await request(`/zones/${zone.id}`, {method: "PATCH", body: JSON.stringify({display_order})});
            }
        });
    }

    zoneList.addEventListener("click", (event) => {
        const button = event.target.closest("button");
        if (!button || button.disabled) {
            return;
        }
        if (button.dataset.move) {
            moveZone(Number(button.dataset.id), button.dataset.move);
        } else if (button.dataset.rename) {
            startRename(Number(button.dataset.rename));
        } else if (button.dataset.cancelRename !== undefined) {
            renderZones();
        } else if (button.dataset.toggleZone) {
            const zone = zoneById(Number(button.dataset.toggleZone));
            runAction(
                () => request(`/zones/${zone.id}`, {method: "PATCH", body: JSON.stringify({is_active: !zone.is_active})}),
                zone.is_active ? `Zona «${zone.name}» desactivada.` : `Zona «${zone.name}» activada.`,
            );
        }
    });

    zoneCreateForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const name = zoneCreateForm.elements.name.value.trim();
        if (!name) {
            return;
        }
        const lastOrder = state.zones.reduce((max, zone) => Math.max(max, zone.display_order), -10);
        const created = await runAction(
            () => request("/zones", {method: "POST", body: JSON.stringify({name, display_order: lastOrder + 10})}),
            "Zona creada.",
        );
        if (created) {
            zoneCreateForm.reset();
        }
    });

    // --- Tables -----------------------------------------------------------

    function tableCard(table) {
        const badges = el("div", {className: "dish-badges"}, [
            table.is_active ? null : el("span", {className: "dish-hidden-badge", text: "Fuera de uso"}),
            table.has_open_session ? el("span", {className: "dish-category", text: "Ocupada ahora"}) : null,
            table.is_active && !table.has_customer_qr ? el("span", {className: "dish-warning-badge", text: "Sin QR"}) : null,
        ]);
        return el("article", {className: `dish-card table-admin-card${table.is_active ? "" : " is-hidden"}`}, [
            el("div", {className: "dish-card-main"}, [
                badges,
                el("h3", {text: table.code}),
                el("p", {className: "dish-description", text: plural(table.capacity, "comensal", "comensales")}),
            ]),
            el("div", {className: "dish-card-side"}, [
                el("div", {className: "row-actions"}, [
                    el("button", {
                        className: "menu-admin-button is-small",
                        text: "Editar",
                        attrs: {type: "button", "data-edit-table": table.id},
                    }),
                    table.is_active ? el("button", {
                        className: "menu-admin-button is-small is-primary",
                        text: table.has_customer_qr ? "Ver QR" : "Crear QR",
                        attrs: {type: "button", "data-qr-table": table.id},
                    }) : null,
                ]),
            ]),
        ]);
    }

    function renderTables() {
        const activeTables = state.tables.filter((table) => table.is_active);
        const missingQr = activeTables.filter((table) => !table.has_customer_qr).length;
        tableSummary.textContent = state.tables.length
            ? `${plural(activeTables.length, "mesa en uso", "mesas en uso")} · ${missingQr ? plural(missingQr, "sin QR", "sin QR") : "todas con QR"}`
            : "Aún no hay mesas.";
        $("generateMissingQrButton").disabled = missingQr === 0;
        $("printAllQrLink").classList.toggle("is-disabled", activeTables.length === missingQr);

        tableGroups.replaceChildren();
        if (!state.tables.length) {
            tableGroups.append(el("p", {
                className: "empty-state",
                text: "Crea tus mesas con «Nueva mesa» o, si tienes muchas, con «Crear varias».",
            }));
            return;
        }

        const groups = [
            ...state.zones.map((zone) => ({title: zone.name, zoneId: zone.id})),
            {title: "Sin zona", zoneId: null},
        ];
        groups.forEach(({title, zoneId}) => {
            const tables = state.tables.filter((table) => table.zone_id === zoneId);
            if (!tables.length) {
                return;
            }
            tableGroups.append(el("section", {className: "table-group"}, [
                el("h3", {className: "table-group-title", text: title}),
                el("div", {className: "table-admin-grid"}, tables.map(tableCard)),
            ]));
        });
    }

    function renderZoneOptions() {
        const select = tableForm.elements.zone_id;
        select.replaceChildren(el("option", {text: "Sin zona", attrs: {value: ""}}));
        state.zones.filter((zone) => zone.is_active).forEach((zone) => {
            select.append(el("option", {text: zone.name, attrs: {value: zone.id}}));
        });
    }

    function openTableDialog({table = null, mode = "single"} = {}) {
        state.editingTableId = table ? table.id : null;
        state.tableDialogMode = mode;
        tableForm.reset();
        renderZoneOptions();
        tableFormError.hidden = true;
        tableForm.querySelectorAll("[data-single-only]").forEach((node) => { node.hidden = mode !== "single"; });
        tableForm.querySelectorAll("[data-batch-only]").forEach((node) => { node.hidden = mode !== "batch"; });

        if (mode === "batch") {
            tableDialogTitle.textContent = "Crear varias mesas";
            tableSubmitButton.textContent = "Crear mesas";
        } else {
            tableDialogTitle.textContent = table ? `Editar mesa ${table.code}` : "Nueva mesa";
            tableSubmitButton.textContent = table ? "Guardar cambios" : "Crear mesa";
        }

        const fields = tableForm.elements;
        fields.code.value = table?.code || "";
        fields.capacity.value = table?.capacity || 4;
        fields.display_order.value = table?.display_order ?? 0;
        fields.is_active.checked = table ? table.is_active : true;
        // An inactive zone is not offered for new assignments, but keep the current one visible.
        if (table?.zone_id && !zoneById(table.zone_id)?.is_active) {
            fields.zone_id.append(el("option", {text: `${zoneById(table.zone_id).name} (inactiva)`, attrs: {value: table.zone_id}}));
        }
        fields.zone_id.value = table?.zone_id ? String(table.zone_id) : "";

        tableDialog.showModal();
        (mode === "batch" ? fields.prefix : fields.code).focus();
    }

    function readPositiveInt(value, label, max) {
        const number = Number(value);
        if (!Number.isInteger(number) || number < 1 || number > max) {
            throw new Error(`${label} debe ser un número entre 1 y ${max}.`);
        }
        return number;
    }

    function readTableForm() {
        const fields = tableForm.elements;
        const capacity = readPositiveInt(fields.capacity.value, "Comensales", 99);
        const zoneId = fields.zone_id.value ? Number(fields.zone_id.value) : null;
        if (state.tableDialogMode === "batch") {
            const from = readPositiveInt(fields.from.value, "Desde", 999);
            const to = readPositiveInt(fields.to.value, "Hasta", 999);
            if (to < from) {
                throw new Error("«Hasta» tiene que ser mayor o igual que «Desde».");
            }
            if (to - from + 1 > 100) {
                throw new Error("Como máximo 100 mesas de una vez.");
            }
            const prefix = fields.prefix.value.trim();
            const lastOrder = state.tables.reduce((max, table) => Math.max(max, table.display_order), 0);
            return Array.from({length: to - from + 1}, (_, offset) => ({
                code: `${prefix}${from + offset}`,
                capacity,
                zone_id: zoneId,
                display_order: lastOrder + (offset + 1) * 10,
            }));
        }
        const code = fields.code.value.trim();
        if (!code) {
            throw new Error("La mesa necesita un nombre o número.");
        }
        return {
            code,
            capacity,
            zone_id: zoneId,
            display_order: Number(fields.display_order.value || 0),
            is_active: fields.is_active.checked,
        };
    }

    tableForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        let payload;
        try {
            payload = readTableForm();
        } catch (error) {
            tableFormError.textContent = error.message;
            tableFormError.hidden = false;
            return;
        }
        if (state.submitting || runAction.isBusy()) {
            return;
        }
        state.submitting = true;
        tableSubmitButton.disabled = true;
        tableFormError.hidden = true;
        let created = 0;
        try {
            if (state.tableDialogMode === "batch") {
                const existing = new Set(state.tables.map((table) => table.code.toLocaleLowerCase("es")));
                const duplicates = payload.filter((table) => existing.has(table.code.toLocaleLowerCase("es")));
                if (duplicates.length) {
                    throw new Error(`Ya existen: ${duplicates.map((table) => table.code).join(", ")}. Cambia el prefijo o los números.`);
                }
                for (const table of payload) {
                    await request("/tables", {method: "POST", body: JSON.stringify(table)});
                    created += 1;
                }
            } else if (state.editingTableId !== null) {
                await request(`/tables/${state.editingTableId}`, {method: "PATCH", body: JSON.stringify(payload)});
            } else {
                await request("/tables", {method: "POST", body: JSON.stringify(payload)});
            }
            tableDialog.close();
            await reload();
            showAlert(
                state.tableDialogMode === "batch"
                    ? `${plural(created, "mesa creada", "mesas creadas")}.`
                    : state.editingTableId !== null ? "Mesa actualizada." : "Mesa creada.",
            );
        } catch (error) {
            const partial = created ? ` Se crearon ${created} antes del error.` : "";
            tableFormError.textContent = `${error.message}${partial}`;
            tableFormError.hidden = false;
            if (created) {
                await reload().catch(() => {});
            }
        } finally {
            state.submitting = false;
            tableSubmitButton.disabled = false;
        }
    });

    // --- QR -----------------------------------------------------------------

    function showQr(table, cacheKey = Date.now()) {
        const pngUrl = `${basePath}/tables/${table.id}/customer-qr.png`;
        qrDialogTitle.textContent = `QR de la mesa ${table.code}`;
        qrImage.alt = `Código QR de la mesa ${table.code}`;
        qrImage.src = `${pngUrl}?v=${cacheKey}`;
        $("downloadQrLink").href = pngUrl;
        $("downloadQrLink").setAttribute("download", `qr-mesa-${table.code}.png`);
        $("printQrLink").href = `/admin/dining/qr-print?table_id=${table.id}`;
        qrDialogError.hidden = true;
        state.qrTableId = table.id;
        if (!qrDialog.open) {
            qrDialog.showModal();
        }
    }

    async function openQr(tableId) {
        const table = tableById(tableId);
        if (!table) return;
        if (table.has_customer_qr) {
            showQr(table);
            return;
        }
        const ok = await runAction(
            () => request(`/tables/${table.id}/customer-qr`, {method: "POST", body: JSON.stringify({rotate: false})}),
            `QR creado para la mesa ${table.code}.`,
        );
        if (ok) {
            showQr(tableById(tableId));
        }
    }

    $("rotateQrButton").addEventListener("click", async () => {
        const table = tableById(state.qrTableId);
        if (!table) return;
        const confirmed = window.confirm(
            `¿Cambiar el QR de la mesa ${table.code}?\n\nEl QR impreso actual dejará de funcionar y los clientes conectados a esa mesa perderán su sesión. Tendrás que imprimir el nuevo.`,
        );
        if (!confirmed) return;
        const ok = await runAction(
            () => request(`/tables/${table.id}/customer-qr`, {method: "POST", body: JSON.stringify({rotate: true})}),
            `QR de la mesa ${table.code} cambiado. Imprime el nuevo.`,
        );
        if (ok) {
            showQr(tableById(table.id));
        }
    });

    $("generateMissingQrButton").addEventListener("click", () => {
        const missing = state.tables.filter((table) => table.is_active && !table.has_customer_qr);
        if (!missing.length) return;
        runAction(async () => {
            for (const table of missing) {
                await request(`/tables/${table.id}/customer-qr`, {method: "POST", body: JSON.stringify({rotate: false})});
            }
        }, `${plural(missing.length, "QR creado", "QR creados")}.`);
    });

    $("printAllQrLink").addEventListener("click", (event) => {
        if (event.currentTarget.classList.contains("is-disabled")) {
            event.preventDefault();
            showAlert("Todavía no hay mesas con QR. Usa «Generar los QR que faltan».", "error");
        }
    });

    // --- Wiring -------------------------------------------------------------

    [tableDialog, qrDialog].forEach((dialog) => {
        dialog.addEventListener("click", (event) => {
            if (event.target.closest("[data-close-dialog]")) {
                dialog.close();
            }
        });
    });

    $("newTableButton").addEventListener("click", () => openTableDialog());
    $("batchTablesButton").addEventListener("click", () => openTableDialog({mode: "batch"}));

    tableGroups.addEventListener("click", (event) => {
        const button = event.target.closest("button");
        if (!button) return;
        if (button.dataset.editTable) {
            openTableDialog({table: tableById(Number(button.dataset.editTable))});
        } else if (button.dataset.qrTable) {
            openQr(Number(button.dataset.qrTable));
        }
    });

    function render() {
        renderZones();
        renderZoneOptions();
        renderTables();
    }

    render();
})();
