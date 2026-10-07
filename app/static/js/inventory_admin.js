(() => {
    const {el, readBootstrap, createAlert, createRequester, createActionRunner, plural} = window.HostAIAdmin;
    const bootstrap = readBootstrap("inventoryAdminBootstrap");
    if (!bootstrap) {
        return;
    }

    const UNIT_LABELS = {g: "g", kg: "kg", ml: "ml", l: "l", unit: "ud."};
    const UNIT_NAMES = {g: "gramos (g)", kg: "kilos (kg)", ml: "mililitros (ml)", l: "litros (l)", unit: "unidades (ud.)"};
    const WASTE_LABELS = {
        expiration: "Caducado",
        spoilage: "Estropeado",
        preparation_error: "Error de preparación",
        breakage: "Rotura o derrame",
        unknown_loss: "Pérdida sin explicar",
        other: "Otro",
    };

    const state = {
        restaurantId: bootstrap.restaurantId,
        units: bootstrap.units || Object.keys(UNIT_LABELS),
        items: bootstrap.items || [],
        editingItemId: null,
        movementItemId: null,
        movementMode: "intake",
        submitting: false,
    };

    const $ = (id) => document.getElementById(id);
    const itemList = $("itemList");
    const itemSearch = $("itemSearch");
    const itemFilter = $("itemFilter");
    const itemDialog = $("itemDialog");
    const itemForm = $("itemForm");
    const movementDialog = $("movementDialog");
    const movementForm = $("movementForm");

    const showAlert = createAlert($("menuAdminAlert"));
    const request = createRequester("/api/inventory");
    const numberFormat = new Intl.NumberFormat("es-ES", {maximumFractionDigits: 3});
    const moneyFormat = new Intl.NumberFormat("es-ES", {style: "currency", currency: bootstrap.currency || "EUR"});

    async function reload() {
        const data = await request(`/management?restaurant_id=${state.restaurantId}`);
        state.items = data.items;
        render();
    }

    const runAction = createActionRunner({reload, showAlert});
    const itemById = (itemId) => state.items.find((item) => item.id === itemId);
    const quantity = (value, unit) => `${numberFormat.format(value)} ${UNIT_LABELS[unit] || unit}`;
    const round3 = (value) => Math.round(value * 1000) / 1000;

    function stockStatus(item) {
        if (!item.is_active) return "inactive";
        if (item.current_stock <= 0) return "out";
        if (item.minimum_stock && item.current_stock <= item.minimum_stock) return "low";
        return "ok";
    }

    // Accepts "12,5" or "12.5"; empty means `fallback`.
    function parseAmount(raw, label, {required = false, positive = false, fallback = null} = {}) {
        const text = String(raw ?? "").trim().replace(/\s/g, "").replace(",", ".");
        if (!text) {
            if (required) throw new Error(`Indica ${label}.`);
            return fallback;
        }
        if (!/^\d+(\.\d+)?$/.test(text)) {
            throw new Error(`${label[0].toUpperCase()}${label.slice(1)} debe ser un número, por ejemplo 2,5.`);
        }
        const value = Number(text);
        if (positive && value <= 0) {
            throw new Error(`${label[0].toUpperCase()}${label.slice(1)} tiene que ser mayor que cero.`);
        }
        return value;
    }

    const toInput = (value) => (value === null || value === undefined ? "" : String(value).replace(".", ","));

    // --- List -----------------------------------------------------------------

    function renderSummary() {
        const counts = {out: 0, low: 0, ok: 0, inactive: 0};
        state.items.forEach((item) => { counts[stockStatus(item)] += 1; });
        $("summaryOut").textContent = counts.out;
        $("summaryLow").textContent = counts.low;
        $("summaryOk").textContent = counts.ok;
        const active = state.items.length - counts.inactive;
        $("itemSummary").textContent = state.items.length
            ? `${plural(active, "ingrediente en uso", "ingredientes en uso")}${counts.inactive ? ` · ${plural(counts.inactive, "retirado", "retirados")}` : ""}`
            : "Aún no hay ingredientes.";
    }

    function filteredItems() {
        const query = itemSearch.value.trim().toLocaleLowerCase("es");
        const filter = itemFilter.value;
        const rank = {out: 0, low: 1, ok: 2, inactive: 3};
        return state.items
            .filter((item) => {
                const status = stockStatus(item);
                if (filter === "restock" && status !== "out" && status !== "low") return false;
                if (filter === "inactive" ? status !== "inactive" : filter === "all" && status === "inactive") return false;
                if (query && !`${item.name} ${item.supplier || ""}`.toLocaleLowerCase("es").includes(query)) return false;
                return true;
            })
            .sort((a, b) => rank[stockStatus(a)] - rank[stockStatus(b)] || a.name.localeCompare(b.name, "es"));
    }

    const STATUS_BADGES = {
        out: ["stock-badge is-critical", "Agotado"],
        low: ["stock-badge is-warning", "Bajo el mínimo"],
        ok: ["stock-badge is-ok", "En orden"],
        inactive: ["dish-hidden-badge", "Retirado"],
    };

    function itemCard(item) {
        const status = stockStatus(item);
        const [badgeClass, badgeText] = STATUS_BADGES[status];
        const limits = [
            item.minimum_stock ? `mínimo ${quantity(item.minimum_stock, item.unit)}` : null,
            item.ideal_stock ? `ideal ${quantity(item.ideal_stock, item.unit)}` : null,
        ].filter(Boolean).join(" · ");
        const details = [
            item.supplier,
            item.cost ? `${moneyFormat.format(item.cost)} / ${UNIT_LABELS[item.unit] || item.unit}` : "Sin coste",
            item.used_in_dishes.length ? `en ${plural(item.used_in_dishes.length, "plato", "platos")}` : "sin recetas",
        ].filter(Boolean).join(" · ");

        const actions = item.is_active ? [
            el("button", {className: "menu-admin-button is-small is-primary", text: "Entrada", attrs: {type: "button", "data-movement": "intake", "data-id": item.id}}),
            el("button", {className: "menu-admin-button is-small", text: "Merma", attrs: {type: "button", "data-movement": "waste", "data-id": item.id}}),
            el("button", {className: "menu-admin-button is-small", text: "Recuento", attrs: {type: "button", "data-movement": "count", "data-id": item.id}}),
            el("button", {className: "menu-admin-button is-small", text: "Editar", attrs: {type: "button", "data-edit-item": item.id}}),
        ] : [
            el("button", {className: "menu-admin-button is-small", text: "Editar", attrs: {type: "button", "data-edit-item": item.id}}),
        ];

        return el("article", {className: `dish-card stock-card is-${status}${item.is_active ? "" : " is-hidden"}`}, [
            el("div", {className: "dish-card-main"}, [
                el("div", {className: "dish-badges"}, [el("span", {className: badgeClass, text: badgeText})]),
                el("h3", {text: item.name}),
                el("p", {className: "dish-description", text: details}),
                item.used_in_dishes.length ? el("p", {className: "dish-allergens", text: `Platos: ${item.used_in_dishes.join(", ")}`}) : null,
            ]),
            el("div", {className: "stock-card-side"}, [
                el("strong", {className: "stock-amount", text: quantity(item.current_stock, item.unit)}),
                limits ? el("span", {className: "stock-limits", text: limits}) : null,
                el("div", {className: "row-actions"}, actions),
            ]),
        ]);
    }

    function renderItems() {
        itemList.replaceChildren();
        const items = filteredItems();
        if (!items.length) {
            itemList.append(el("p", {
                className: "empty-state",
                text: state.items.length ? "Ningún ingrediente coincide con el filtro." : "Crea tu primer ingrediente con «Nuevo ingrediente».",
            }));
            return;
        }
        items.forEach((item) => itemList.append(itemCard(item)));
    }

    // --- Item dialog ------------------------------------------------------------

    function setFormError(form, message) {
        const box = form.querySelector(".dish-form-error");
        box.textContent = message || "";
        box.hidden = !message;
    }

    function openItemDialog(item = null) {
        state.editingItemId = item ? item.id : null;
        itemForm.reset();
        setFormError(itemForm, null);
        const fields = itemForm.elements;
        fields.unit.replaceChildren(...state.units.map((unit) => el("option", {text: UNIT_NAMES[unit] || unit, attrs: {value: unit}})));
        itemForm.querySelectorAll("[data-create-only]").forEach((node) => { node.hidden = Boolean(item); });
        itemForm.querySelectorAll("[data-edit-only]").forEach((node) => { node.hidden = !item; });

        $("itemDialogTitle").textContent = item ? `Editar ${item.name}` : "Nuevo ingrediente";
        $("itemSubmitButton").textContent = item ? "Guardar cambios" : "Crear ingrediente";
        fields.name.value = item?.name || "";
        fields.unit.value = item?.unit || "kg";
        fields.unit.disabled = Boolean(item?.unit_locked);
        $("unitLockedHint").hidden = !item?.unit_locked;
        fields.minimum_stock.value = toInput(item?.minimum_stock || "");
        fields.ideal_stock.value = toInput(item?.ideal_stock || "");
        fields.cost.value = toInput(item?.cost);
        fields.supplier.value = item?.supplier || "";
        fields.is_active.checked = item ? item.is_active : true;
        itemDialog.showModal();
        fields.name.focus();
    }

    function readItemForm() {
        const fields = itemForm.elements;
        const name = fields.name.value.trim();
        if (!name) throw new Error("El ingrediente necesita un nombre.");
        const minimum = parseAmount(fields.minimum_stock.value, "el stock mínimo", {fallback: 0});
        const ideal = parseAmount(fields.ideal_stock.value, "el stock ideal", {fallback: 0});
        if (ideal && minimum && ideal < minimum) throw new Error("El stock ideal no puede ser menor que el mínimo.");
        const payload = {
            name,
            minimum_stock: minimum,
            ideal_stock: ideal,
            cost: parseAmount(fields.cost.value, "el coste"),
            supplier: fields.supplier.value.trim() || null,
        };
        if (!fields.unit.disabled) payload.unit = fields.unit.value;
        if (state.editingItemId === null) {
            payload.restaurant_id = state.restaurantId;
            payload.current_stock = parseAmount(fields.current_stock.value, "el stock inicial", {fallback: 0});
        } else {
            payload.is_active = fields.is_active.checked;
        }
        return payload;
    }

    async function submitDialog(form, dialog, buildRequest, successMessage) {
        let call;
        try {
            call = buildRequest();
        } catch (error) {
            setFormError(form, error.message);
            return;
        }
        if (call === null) return;
        if (state.submitting || runAction.isBusy()) return;
        state.submitting = true;
        const submit = form.querySelector('button[type="submit"]');
        submit.disabled = true;
        setFormError(form, null);
        try {
            await request(call.path, {method: call.method, body: JSON.stringify(call.body)});
            dialog.close();
            await reload();
            showAlert(typeof successMessage === "function" ? successMessage() : successMessage);
        } catch (error) {
            setFormError(form, error.message);
        } finally {
            state.submitting = false;
            submit.disabled = false;
        }
    }

    itemForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const isEdit = state.editingItemId !== null;
        submitDialog(itemForm, itemDialog, () => ({
            path: isEdit ? `/items/${state.editingItemId}` : "/items",
            method: isEdit ? "PATCH" : "POST",
            body: readItemForm(),
        }), isEdit ? "Ingrediente actualizado." : "Ingrediente creado.");
    });

    // --- Movement dialog --------------------------------------------------------

    function openMovementDialog(itemId, mode) {
        const item = itemById(itemId);
        if (!item) return;
        state.movementItemId = itemId;
        state.movementMode = mode;
        movementForm.reset();
        setFormError(movementForm, null);
        movementForm.querySelectorAll("[data-mode]").forEach((node) => {
            node.hidden = !node.dataset.mode.split(" ").includes(mode);
        });
        const unit = UNIT_LABELS[item.unit] || item.unit;
        const titles = {intake: `Entrada de ${item.name}`, waste: `Merma de ${item.name}`, count: `Recuento de ${item.name}`};
        const buttons = {intake: "Registrar entrada", waste: "Registrar merma", count: "Guardar recuento"};
        $("movementDialogTitle").textContent = titles[mode];
        $("movementSubmitButton").textContent = buttons[mode];
        $("quantityLabel").textContent = mode === "intake" ? `Cantidad recibida (${unit}) *` : `Cantidad perdida (${unit}) *`;
        $("countedLabel").textContent = `Cantidad que hay ahora (${unit}) *`;
        $("movementContext").textContent = `Stock actual en el sistema: ${quantity(item.current_stock, item.unit)}.`
            + (mode === "waste" && !item.cost ? " Este ingrediente no tiene coste: añádelo en «Editar» antes de registrar mermas." : "");
        $("countPreview").textContent = "";
        movementDialog.showModal();
        (mode === "count" ? movementForm.elements.counted : movementForm.elements.quantity).focus();
    }

    movementForm.elements.counted.addEventListener("input", () => {
        const item = itemById(state.movementItemId);
        let counted;
        try {
            counted = parseAmount(movementForm.elements.counted.value, "la cantidad");
        } catch (error) {
            $("countPreview").textContent = "";
            return;
        }
        if (counted === null || !item) {
            $("countPreview").textContent = "";
            return;
        }
        const diff = round3(counted - item.current_stock);
        $("countPreview").textContent = diff === 0
            ? "Coincide con el sistema: no hay nada que ajustar."
            : `Se ${diff > 0 ? "sumarán" : "restarán"} ${quantity(Math.abs(diff), item.unit)} para que el sistema coincida con el almacén.`;
    });

    function buildMovementRequest() {
        const item = itemById(state.movementItemId);
        const fields = movementForm.elements;
        const base = {restaurant_id: state.restaurantId, inventory_item_id: item.id, unit: item.unit};
        if (state.movementMode === "intake") {
            return {
                path: "/purchase-intakes",
                method: "POST",
                body: {
                    ...base,
                    quantity: parseAmount(fields.quantity.value, "la cantidad recibida", {required: true, positive: true}),
                    unit_cost: parseAmount(fields.unit_cost.value, "el precio", {positive: true}),
                    reference: fields.reference.value.trim() || null,
                    reason: "Compra a proveedor",
                },
            };
        }
        if (state.movementMode === "waste") {
            const category = fields.loss_category.value;
            return {
                path: "/waste-losses",
                method: "POST",
                body: {
                    ...base,
                    quantity: parseAmount(fields.quantity.value, "la cantidad perdida", {required: true, positive: true}),
                    loss_category: category,
                    reason: WASTE_LABELS[category],
                    note: fields.note.value.trim() || null,
                },
            };
        }
        const counted = parseAmount(fields.counted.value, "la cantidad que hay ahora", {required: true});
        const diff = round3(counted - item.current_stock);
        if (diff === 0) {
            movementDialog.close();
            showAlert(`El recuento de ${item.name} coincide con el sistema. No se ha cambiado nada.`);
            return null;
        }
        return {
            path: "/adjustments",
            method: "POST",
            body: {...base, stock_difference: diff, reason: "Recuento de almacén", note: fields.note.value.trim() || null},
        };
    }

    movementForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const item = itemById(state.movementItemId);
        const messages = {
            intake: `Entrada registrada en ${item.name}.`,
            waste: `Merma registrada en ${item.name}.`,
            count: `Recuento guardado: ${item.name} ya coincide con el almacén.`,
        };
        submitDialog(movementForm, movementDialog, buildMovementRequest, messages[state.movementMode]);
    });

    // --- Wiring -------------------------------------------------------------------

    [itemDialog, movementDialog].forEach((dialog) => {
        dialog.addEventListener("click", (event) => {
            if (event.target.closest("[data-close-dialog]")) dialog.close();
        });
    });

    $("newItemButton").addEventListener("click", () => openItemDialog());

    itemList.addEventListener("click", (event) => {
        const button = event.target.closest("button");
        if (!button) return;
        if (button.dataset.editItem) {
            openItemDialog(itemById(Number(button.dataset.editItem)));
        } else if (button.dataset.movement) {
            openMovementDialog(Number(button.dataset.id), button.dataset.movement);
        }
    });

    document.querySelectorAll("[data-summary-filter]").forEach((button) => {
        button.addEventListener("click", () => {
            itemFilter.value = button.dataset.summaryFilter;
            renderItems();
            itemList.scrollIntoView({behavior: "smooth", block: "start"});
        });
    });

    [itemSearch, itemFilter].forEach((control) => control.addEventListener("input", renderItems));

    function render() {
        renderSummary();
        renderItems();
    }

    render();
})();
