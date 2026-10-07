(() => {
    const {el, readBootstrap, createAlert, createRequester, plural} = window.HostAIAdmin;
    const bootstrap = readBootstrap("purchasingAdminBootstrap");
    if (!bootstrap) {
        return;
    }

    const UNIT_LABELS = {g: "g", kg: "kg", ml: "ml", l: "l", unit: "ud."};
    const PRIORITY_BADGES = {
        urgent: ["stock-badge is-critical", "Urgente"],
        high: ["stock-badge is-warning", "Pronto"],
        medium: ["dish-category", "Reponer"],
        monitor: ["dish-category", "Reponer"],
        low: ["dish-category", "Reponer"],
    };

    const state = {
        restaurantId: bootstrap.restaurantId,
        restaurantName: bootstrap.restaurantName,
        coverageDays: bootstrap.coverage_days,
        range: bootstrap.range,
        groups: bootstrap.groups || [],
        // Per-line edits survive re-renders: item id -> {included, quantity}.
        edits: new Map(),
        receivingGroup: null,
        submitting: false,
    };

    const $ = (id) => document.getElementById(id);
    const groupsBox = $("purchaseGroups");
    const receiveDialog = $("receiveDialog");
    const receiveForm = $("receiveForm");

    const showAlert = createAlert($("menuAdminAlert"));
    const request = createRequester("/api/inventory");
    const money = new Intl.NumberFormat("es-ES", {style: "currency", currency: bootstrap.currency || "EUR"});
    const number = new Intl.NumberFormat("es-ES", {maximumFractionDigits: 3});
    const inputNumber = new Intl.NumberFormat("es-ES", {maximumFractionDigits: 3, useGrouping: false});
    const quantity = (value, unit) => `${number.format(value)} ${UNIT_LABELS[unit] || unit}`;

    function parseAmount(raw, label) {
        const text = String(raw ?? "").trim().replace(/\s|€/g, "").replace(",", ".");
        if (text === "") return 0;
        if (!/^\d+(\.\d+)?$/.test(text)) throw new Error(`${label} debe ser un número, por ejemplo 2,5.`);
        return Number(text);
    }

    const lineEdit = (line) => state.edits.get(line.inventory_item_id) || {included: true, quantity: line.suggested_quantity};

    function selectedLines(group) {
        return group.lines
            .map((line) => ({line, ...lineEdit(line)}))
            .filter(({included, quantity: amount}) => included && amount > 0);
    }

    function reasonText(line) {
        const parts = [`Tienes ${quantity(line.current_stock, line.unit)}`];
        if (line.average_daily_consumption) {
            parts.push(`gastas ${quantity(line.average_daily_consumption, line.unit)} al día`);
            if (line.estimated_days_remaining !== null) {
                parts.push(`te da para ${number.format(Math.floor(line.estimated_days_remaining))} ${Math.floor(line.estimated_days_remaining) === 1 ? "día" : "días"}`);
            }
        }
        const target = line.basis === "consumption"
            ? `objetivo ${quantity(line.target_stock, line.unit)} para ${state.coverageDays} días de consumo`
            : line.basis === "ideal"
                ? `objetivo: tu stock ideal (${quantity(line.target_stock, line.unit)})`
                : `objetivo: tu stock mínimo (${quantity(line.target_stock, line.unit)})`;
        parts.push(target);
        return `${parts.join(", ")}.`;
    }

    // --- Rendering ----------------------------------------------------------------

    function groupTotal(group) {
        return selectedLines(group).reduce((sum, {line, quantity: amount}) => sum + (line.unit_cost ? amount * line.unit_cost : 0), 0);
    }

    function renderGroups() {
        groupsBox.replaceChildren();
        if (!state.groups.length) {
            groupsBox.append(el("section", {className: "menu-admin-panel"}, [
                el("p", {className: "empty-state", text: "No hace falta pedir nada: todo está por encima de su objetivo para estos días."}),
            ]));
            return;
        }

        state.groups.forEach((group, groupIndex) => {
            const selected = selectedLines(group);
            const lines = group.lines.map((line) => {
                const edit = lineEdit(line);
                const [badgeClass, badgeText] = PRIORITY_BADGES[line.priority] || PRIORITY_BADGES.medium;
                const checkbox = el("input", {attrs: {type: "checkbox", "aria-label": `Incluir ${line.name}`, "data-include": line.inventory_item_id}});
                checkbox.checked = edit.included;
                const amountInput = el("input", {attrs: {type: "text", inputmode: "decimal", "aria-label": `Cantidad de ${line.name}`, "data-quantity": line.inventory_item_id}});
                amountInput.value = inputNumber.format(edit.quantity);
                return el("article", {className: `purchase-line${edit.included ? "" : " is-excluded"}`}, [
                    el("label", {className: "purchase-check"}, [checkbox]),
                    el("div", {className: "purchase-line-main"}, [
                        el("div", {className: "dish-badges"}, [
                            el("span", {className: badgeClass, text: badgeText}),
                            line.blocked_dishes_count ? el("span", {className: "dish-warning-badge", text: `${plural(line.blocked_dishes_count, "plato", "platos")} sin stock`}) : null,
                        ]),
                        el("strong", {text: line.name}),
                        el("p", {className: "purchase-reason", text: reasonText(line)}),
                    ]),
                    el("div", {className: "purchase-line-amount"}, [
                        el("div", {className: "input-suffix"}, [amountInput, el("span", {text: UNIT_LABELS[line.unit] || line.unit})]),
                        el("span", {className: "purchase-line-cost", text: line.unit_cost ? money.format(edit.quantity * line.unit_cost) : "sin coste"}),
                    ]),
                ]);
            });

            groupsBox.append(el("section", {className: "menu-admin-panel purchase-group", attrs: {"data-group": groupIndex}}, [
                el("div", {className: "menu-admin-panel-heading"}, [
                    el("div", {}, [
                        el("h2", {text: group.supplier}),
                        el("p", {text: `${plural(selected.length, "producto", "productos")} · ${money.format(groupTotal(group))} aprox.${group.has_missing_costs ? " (faltan costes)" : ""}`}),
                    ]),
                    el("div", {className: "row-actions purchase-actions"}, [
                        el("button", {className: "menu-admin-button is-small", text: "Copiar pedido", attrs: {type: "button", "data-copy": groupIndex, disabled: !selected.length}}),
                        el("button", {className: "menu-admin-button is-small", text: "Imprimir", attrs: {type: "button", "data-print": groupIndex, disabled: !selected.length}}),
                        el("button", {className: "menu-admin-button is-small is-primary", text: "Recibir mercancía", attrs: {type: "button", "data-receive": groupIndex, disabled: !selected.length}}),
                    ]),
                ]),
                el("div", {className: "purchase-lines"}, lines),
            ]));
        });
    }

    // --- Settings -------------------------------------------------------------------

    $("coverageInput").value = state.coverageDays;
    $("rangeInput").value = state.range;

    async function reload() {
        const params = new URLSearchParams({
            restaurant_id: state.restaurantId,
            coverage_days: state.coverageDays,
            range: state.range,
        });
        const data = await request(`/purchase-list?${params}`);
        state.groups = data.groups;
        state.edits.clear();
        renderGroups();
    }

    $("purchaseSettings").addEventListener("submit", async (event) => {
        event.preventDefault();
        const days = Number($("coverageInput").value);
        if (!Number.isInteger(days) || days < 1 || days > 60) {
            showAlert("Los días a cubrir deben estar entre 1 y 60.", "error");
            return;
        }
        state.coverageDays = days;
        state.range = $("rangeInput").value;
        try {
            await reload();
            showAlert(`Pedido recalculado para ${plural(days, "día", "días")}.`);
        } catch (error) {
            showAlert(error.message, "error");
        }
    });

    // --- Editing lines ----------------------------------------------------------------

    groupsBox.addEventListener("change", (event) => {
        const target = event.target;
        const itemId = Number(target.dataset.include || target.dataset.quantity);
        if (!itemId) return;
        const line = state.groups.flatMap((group) => group.lines).find((item) => item.inventory_item_id === itemId);
        const edit = {...lineEdit(line)};
        if (target.dataset.include) {
            edit.included = target.checked;
        } else {
            try {
                edit.quantity = parseAmount(target.value, "La cantidad");
            } catch (error) {
                showAlert(error.message, "error");
            }
        }
        state.edits.set(itemId, edit);
        renderGroups();
    });

    // --- Copy & print ------------------------------------------------------------------

    function orderText(group) {
        const date = new Intl.DateTimeFormat("es-ES", {weekday: "long", day: "numeric", month: "long"}).format(new Date());
        const lines = selectedLines(group).map(({line, quantity: amount}) => `- ${line.name}: ${quantity(amount, line.unit)}`);
        return [`Hola, os escribo de ${state.restaurantName}. Pedido del ${date}:`, "", ...lines, "", "Gracias."].join("\n");
    }

    groupsBox.addEventListener("click", async (event) => {
        const button = event.target.closest("button");
        if (!button || button.disabled) return;
        if (button.dataset.copy) {
            const group = state.groups[Number(button.dataset.copy)];
            try {
                await navigator.clipboard.writeText(orderText(group));
                showAlert(`Pedido para ${group.supplier} copiado. Pégalo en WhatsApp o en un email.`);
            } catch (error) {
                window.prompt("Copia el pedido:", orderText(group));
            }
        } else if (button.dataset.print) {
            const section = button.closest(".purchase-group");
            section.classList.add("is-print-target");
            document.body.dataset.printGroup = button.dataset.print;
            window.print();
        } else if (button.dataset.receive) {
            openReceive(Number(button.dataset.receive));
        }
    });

    window.addEventListener("afterprint", () => {
        delete document.body.dataset.printGroup;
        document.querySelectorAll(".is-print-target").forEach((node) => node.classList.remove("is-print-target"));
    });

    // --- Receiving goods -----------------------------------------------------------------

    function openReceive(groupIndex) {
        const group = state.groups[groupIndex];
        state.receivingGroup = groupIndex;
        receiveForm.reset();
        $("receiveFormError").hidden = true;
        $("receiveDialogTitle").textContent = `Recibir mercancía de ${group.supplier}`;
        $("receiveLines").replaceChildren(...selectedLines(group).map(({line, quantity: amount}) => {
            const received = el("input", {attrs: {type: "text", inputmode: "decimal", "data-received": line.inventory_item_id, "aria-label": `Recibido de ${line.name}`}});
            received.value = inputNumber.format(amount);
            const price = el("input", {attrs: {type: "text", inputmode: "decimal", "data-price": line.inventory_item_id, "aria-label": `Precio de ${line.name}`, placeholder: "Opcional"}});
            price.value = line.unit_cost ? inputNumber.format(line.unit_cost) : "";
            return el("article", {className: "recipe-line receive-line"}, [
                el("div", {className: "recipe-line-name"}, [
                    el("strong", {text: line.name}),
                    el("span", {text: `Pedido: ${quantity(amount, line.unit)}`}),
                ]),
                el("label", {className: "recipe-line-field"}, [el("span", {text: `Recibido (${UNIT_LABELS[line.unit] || line.unit})`}), received]),
                el("label", {className: "recipe-line-field"}, [el("span", {text: `Precio por ${UNIT_LABELS[line.unit] || line.unit} (€)`}), price]),
            ]);
        }));
        receiveDialog.showModal();
    }

    receiveForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (state.submitting) return;
        const group = state.groups[state.receivingGroup];
        const reference = receiveForm.elements.reference.value.trim() || null;
        let entries;
        try {
            entries = selectedLines(group).map(({line}) => ({
                line,
                received: parseAmount(receiveForm.querySelector(`[data-received="${line.inventory_item_id}"]`).value, `Lo recibido de ${line.name}`),
                price: parseAmount(receiveForm.querySelector(`[data-price="${line.inventory_item_id}"]`).value, `El precio de ${line.name}`),
            })).filter((entry) => entry.received > 0);
        } catch (error) {
            $("receiveFormError").textContent = error.message;
            $("receiveFormError").hidden = false;
            return;
        }
        if (!entries.length) {
            $("receiveFormError").textContent = "No has indicado ninguna cantidad recibida.";
            $("receiveFormError").hidden = false;
            return;
        }

        state.submitting = true;
        $("receiveSubmitButton").disabled = true;
        const done = [];
        try {
            for (const {line, received, price} of entries) {
                await request("/purchase-intakes", {
                    method: "POST",
                    body: JSON.stringify({
                        restaurant_id: state.restaurantId,
                        inventory_item_id: line.inventory_item_id,
                        quantity: received,
                        unit: line.unit,
                        unit_cost: price > 0 ? price : null,
                        reason: `Pedido a ${group.supplier}`.slice(0, 80),
                        reference,
                    }),
                });
                done.push(line.name);
            }
            receiveDialog.close();
            await reload();
            showAlert(`Entrada registrada en el stock: ${done.join(", ")}.`);
        } catch (error) {
            if (done.length) {
                // Never leave a half-applied form open: resubmitting would double the stock.
                receiveDialog.close();
                await reload().catch(() => {});
                showAlert(`Se registraron ${done.join(", ")}, pero el resto falló: ${error.message} Revisa esos productos y regístralos desde «Inventario».`, "error");
            } else {
                $("receiveFormError").textContent = error.message;
                $("receiveFormError").hidden = false;
            }
        } finally {
            state.submitting = false;
            $("receiveSubmitButton").disabled = false;
        }
    });

    receiveDialog.addEventListener("click", (event) => {
        if (event.target.closest("[data-close-dialog]")) receiveDialog.close();
    });

    renderGroups();
})();
