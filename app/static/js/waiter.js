const workspace = document.querySelector("[data-waiter-workspace]");
const bootstrapElement = document.getElementById("waiterBootstrap");

if (workspace && bootstrapElement) {
    const state = {
        ...JSON.parse(bootstrapElement.textContent),
        currentSessionId: null,
        currentTableCode: null,
        orders: [],
        currentSettlementId: null,
        payments: [],
        paymentBalance: null,
        paymentIdempotencyKey: null,
    };

    const roomGrid = document.getElementById("roomGrid");
    const zoneFilter = document.querySelector(".zone-filter");
    const sessionWorkspace = document.getElementById("sessionWorkspace");
    const orderList = document.getElementById("orderList");
    const dishPicker = document.getElementById("dishPicker");
    const alertBox = document.getElementById("waiterAlert");
    const freeTableCount = document.getElementById("freeTableCount");
    const occupiedTableCount = document.getElementById("occupiedTableCount");
    const sessionTitle = document.getElementById("sessionTitle");
    const sessionMeta = document.getElementById("sessionMeta");
    const sessionEyebrow = document.getElementById("sessionEyebrow");
    const sessionLayout = document.querySelector(".session-layout");
    const settleSessionButton = document.getElementById("settleSessionButton");
    const cancelTableButton = document.getElementById("cancelTableButton");
    const paymentPanel = document.getElementById("paymentPanel");
    const paymentStatus = document.getElementById("paymentStatus");
    const paymentTotal = document.getElementById("paymentTotal");
    const paymentPaid = document.getElementById("paymentPaid");
    const paymentRemaining = document.getElementById("paymentRemaining");
    const paymentForm = document.getElementById("paymentForm");
    const paymentAmount = document.getElementById("paymentAmount");
    const paymentMethod = document.getElementById("paymentMethod");
    const paymentReference = document.getElementById("paymentReference");
    const paymentHistory = document.getElementById("paymentHistory");

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const randomKey = () => {
        if (globalThis.crypto?.randomUUID) {
            return globalThis.crypto.randomUUID();
        }
        return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    };

    const formatMoney = (value) => new Intl.NumberFormat("es-ES", {
        style: "currency",
        currency: state.currency,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(value);

    const minutesOpen = (openedAt) => {
        const elapsed = Math.max(0, Date.now() - new Date(openedAt).getTime());
        const minutes = Math.floor(elapsed / 60000);
        return minutes < 60
            ? `${minutes} min`
            : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
    };

    const showAlert = (message, success = false) => {
        alertBox.textContent = message;
        alertBox.classList.toggle("is-success", success);
        alertBox.hidden = false;
        window.clearTimeout(showAlert.timeout);
        showAlert.timeout = window.setTimeout(() => {
            alertBox.hidden = true;
        }, 6000);
    };

    const requestJson = async (url, options = {}) => {
        const response = await window.HostAISecurity.fetch(url, {
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                ...(options.headers || {}),
            },
            ...options,
        });
        if (response.status === 204) {
            return null;
        }
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error?.message || "No se pudo completar la acción.");
        }
        return payload;
    };

    const withBusyButton = async (button, callback) => {
        if (button.disabled) {
            return;
        }
        button.disabled = true;
        try {
            await callback();
        } catch (error) {
            showAlert(error.message);
            if (state.currentSessionId && !state.currentSettlementId) {
                await loadOrders().catch(() => {});
            }
        } finally {
            button.disabled = false;
        }
    };

    const tableCardHtml = (item) => {
        const table = item.table;
        const currentSession = item.current_session;
        const zoneId = table.zone_id ?? "none";
        if (!currentSession) {
            return `
                <article class="table-card is-free" data-table-card data-table-id="${table.id}" data-zone-id="${zoneId}">
                    <div class="table-card-top">
                        <div><span class="table-status">Libre</span><h2>${escapeHtml(table.code)}</h2></div>
                        <span class="table-capacity">${table.capacity} pax</span>
                    </div>
                    <form class="open-table-form" data-open-table="${table.id}">
                        <label><span>Comensales</span><input name="guest_count" type="number" min="1" inputmode="numeric" value="2" required></label>
                        <label><span>Nota opcional</span><input name="note" type="text" maxlength="1000" placeholder="Trona, celebración…"></label>
                        <button type="submit" class="primary-touch-button">Abrir mesa</button>
                    </form>
                </article>`;
        }
        return `
            <article class="table-card is-occupied" data-table-card data-table-id="${table.id}" data-zone-id="${zoneId}">
                <div class="table-card-top">
                    <div><span class="table-status">Ocupada</span><h2>${escapeHtml(table.code)}</h2></div>
                    <span class="table-capacity">${table.capacity} pax</span>
                </div>
                <div class="table-session-meta">
                    <span>${currentSession.guest_count ?? "—"} comensales</span>
                    <span>${minutesOpen(currentSession.opened_at)}</span>
                    <span>${item.active_order_count ?? 0} pedidos activos</span>
                </div>
                <button type="button" class="primary-touch-button" data-open-session="${currentSession.id}" data-table-code="${escapeHtml(table.code)}">Abrir sesión</button>
            </article>`;
    };

    const renderRoom = () => {
        roomGrid.innerHTML = state.room.tables.length
            ? state.room.tables.map(tableCardHtml).join("")
            : `<div class="waiter-empty"><h2>No hay mesas activas</h2><p>Un owner o manager puede configurarlas desde la API de sala.</p></div>`;
        freeTableCount.textContent = state.room.free_tables;
        occupiedTableCount.textContent = state.room.occupied_tables;
    };

    const refreshRoom = async () => {
        state.room = await requestJson(`/api/dining/${state.restaurantId}/room`);
        const orderCountRequests = state.room.tables.map(async (item) => {
            if (!item.current_session) {
                item.active_order_count = 0;
                return;
            }
            const orders = await requestJson(
                `/api/orders/${state.restaurantId}/sessions/${item.current_session.id}`,
            );
            item.active_order_count = orders.filter(
                (order) => [
                    "draft",
                    "draft_customer",
                    "submitted_customer",
                    "submitted",
                ].includes(order.status),
            ).length;
        });
        await Promise.all(orderCountRequests);
        renderRoom();
    };

    const dishCardHtml = (dish) => `
        <article class="dish-pick-card" data-dish-card data-search="${escapeHtml(`${dish.name} ${dish.description} ${dish.allergens}`.toLowerCase())}">
            <div>
                <h4>${escapeHtml(dish.name)}</h4>
                <p class="dish-price">${formatMoney(dish.price)}</p>
            </div>
            <p>${escapeHtml(dish.description || "Sin descripción")}</p>
            <p class="allergen-note"><strong>Alérgenos:</strong> ${escapeHtml(dish.allergens || "No informados")}</p>
            <input class="dish-note" data-dish-note="${dish.id}" type="text" maxlength="1000" placeholder="Observación: sin cebolla…">
            <button type="button" class="primary-touch-button" data-add-dish="${dish.id}">Añadir</button>
        </article>`;

    const renderDishes = () => {
        dishPicker.innerHTML = state.dishes.length
            ? state.dishes.map(dishCardHtml).join("")
            : `<div class="waiter-empty"><h2>Carta vacía</h2><p>No hay platos disponibles en este local.</p></div>`;
    };

    const statusLabel = {
        draft: "Borrador",
        draft_customer: "Cliente preparando",
        submitted_customer: "Pendiente de aprobación",
        submitted: "Enviado",
        cancelled: "Cancelado",
        completed: "Completado",
    };
    const kitchenStatusLabel = {
        pending: "Cocina pendiente",
        preparing: "En preparación",
        ready: "Lista para servir",
        served: "Servida",
        cancelled: "Cocina cancelada",
    };

    const lineHtml = (line, editable) => `
        <div class="line-item">
            <div class="line-row">
                <strong>${escapeHtml(line.dish_name)}</strong>
                <span>${formatMoney(line.subtotal)}</span>
            </div>
            ${editable ? `
                <div class="quantity-control">
                    <button class="icon-touch-button" type="button" data-line-quantity="${line.id}" data-quantity="${line.quantity - 1}" ${line.quantity <= 1 ? "disabled" : ""} aria-label="Restar unidad">−</button>
                    <output>${line.quantity}</output>
                    <button class="icon-touch-button" type="button" data-line-quantity="${line.id}" data-quantity="${line.quantity + 1}" aria-label="Sumar unidad">+</button>
                </div>
                <div class="line-actions">
                    <label class="line-note">
                        <span>Observación</span>
                        <input data-line-note="${line.id}" type="text" maxlength="1000" value="${escapeHtml(line.note || "")}">
                    </label>
                    <button class="danger-touch-button" type="button" data-delete-line="${line.id}" aria-label="Eliminar ${escapeHtml(line.dish_name)}">×</button>
                </div>
                <button class="secondary-touch-button" type="button" data-save-note="${line.id}">Guardar observación</button>
            ` : `<p class="allergen-note">${escapeHtml(line.note || "Sin observaciones")}</p>`}
        </div>`;

    const orderHtml = (order) => {
        const editable = order.status === "draft";
        let actions = "";
        if (editable) {
            actions = `
                <button class="danger-touch-button" type="button" data-cancel-order="${order.id}">Cancelar</button>
                <button class="primary-touch-button" type="button" data-submit-order="${order.id}">Revisar y enviar</button>`;
        } else if (order.status === "submitted_customer") {
            actions = `
                <button class="danger-touch-button" type="button" data-reject-customer-order="${order.id}">Rechazar</button>
                <button class="primary-touch-button" type="button" data-approve-customer-order="${order.id}">Aceptar pedido</button>`;
        } else if (order.status === "submitted") {
            if (!order.kitchen_status || order.kitchen_status === "pending") {
                actions = `<button class="danger-touch-button" type="button" data-cancel-order="${order.id}">Cancelar</button>`;
            } else if (order.kitchen_status === "served") {
                actions = `<button class="primary-touch-button" type="button" data-fulfill-order="${order.id}">Confirmar servicio</button>`;
            }
        }
        return `
            <article class="order-card" data-order-id="${order.id}">
                <div class="order-heading">
                    <h4>Pedido #${order.id}${order.is_customer_order ? " · Cliente" : ""}</h4>
                    <div>
                        <span class="status-chip">${statusLabel[order.status]}</span>
                        ${order.kitchen_status
                            ? `<span class="status-chip">${kitchenStatusLabel[order.kitchen_status]}</span>`
                            : ""}
                    </div>
                </div>
                <div class="order-lines">
                    ${order.lines.length
                        ? order.lines.map((line) => lineHtml(line, editable)).join("")
                        : `<p class="allergen-note">Añade el primer plato de esta ronda.</p>`}
                </div>
                <div class="order-total">
                    <span>${order.total_units} uds.</span>
                    <strong>${formatMoney(order.total_amount)}</strong>
                </div>
                ${actions ? `<div class="order-actions">${actions}</div>` : ""}
            </article>`;
    };

    const renderOrders = () => {
        orderList.innerHTML = state.orders.length
            ? state.orders.map(orderHtml).join("")
            : `<div class="waiter-empty"><h2>Sin pedidos</h2><p>Añade un plato para iniciar la primera ronda.</p></div>`;
        const completedOrders = state.orders.filter(
            (order) => order.status === "completed",
        );
        const hasPendingOrders = state.orders.some(
            (order) => [
                "draft",
                "draft_customer",
                "submitted_customer",
                "submitted",
            ].includes(order.status),
        );
        const canSettle = completedOrders.length > 0
            && !hasPendingOrders
            && completedOrders.every(
                (order) => order.fulfillment_status === "completed",
            );
        settleSessionButton.hidden = !canSettle;
        cancelTableButton.hidden = completedOrders.length > 0;
    };

    const loadOrders = async () => {
        state.orders = await requestJson(
            `/api/orders/${state.restaurantId}/sessions/${state.currentSessionId}`,
        );
        renderOrders();
    };

    const openSession = async (sessionId, tableCode) => {
        state.currentSessionId = Number(sessionId);
        state.currentTableCode = tableCode;
        state.currentSettlementId = null;
        state.payments = [];
        state.paymentBalance = null;
        state.paymentIdempotencyKey = null;
        sessionLayout.hidden = false;
        paymentPanel.hidden = true;
        sessionEyebrow.textContent = "Sesión activa";
        sessionTitle.textContent = `Mesa ${tableCode}`;
        const tableState = state.room.tables.find(
            (item) => item.current_session?.id === state.currentSessionId,
        );
        sessionMeta.textContent = tableState?.current_session
            ? `${tableState.current_session.guest_count ?? "—"} comensales · ${minutesOpen(tableState.current_session.opened_at)}`
            : "Sesión activa";
        roomGrid.hidden = true;
        zoneFilter.hidden = true;
        sessionWorkspace.hidden = false;
        renderDishes();
        await loadOrders();
        window.scrollTo({ top: 0, behavior: "smooth" });
    };

    const showRoom = async () => {
        state.currentSessionId = null;
        state.currentTableCode = null;
        state.currentSettlementId = null;
        state.payments = [];
        state.paymentBalance = null;
        state.paymentIdempotencyKey = null;
        sessionLayout.hidden = false;
        paymentPanel.hidden = true;
        sessionWorkspace.hidden = true;
        roomGrid.hidden = false;
        zoneFilter.hidden = false;
        await refreshRoom();
        window.scrollTo({ top: 0, behavior: "smooth" });
    };

    const createOrder = async () => {
        const order = await requestJson(
            `/api/orders/${state.restaurantId}/sessions/${state.currentSessionId}`,
            {
                method: "POST",
                body: JSON.stringify({ idempotency_key: randomKey() }),
            },
        );
        await loadOrders();
        return order;
    };

    const currentDraftOrder = async () => {
        let draft = state.orders.find((order) => order.status === "draft");
        if (!draft) {
            draft = await createOrder();
        }
        return draft;
    };

    roomGrid.addEventListener("submit", (event) => {
        const form = event.target.closest("[data-open-table]");
        if (!form) {
            return;
        }
        event.preventDefault();
        const button = form.querySelector("button[type='submit']");
        withBusyButton(button, async () => {
            const formData = new FormData(form);
            const serviceSession = await requestJson(
                `/api/dining/${state.restaurantId}/tables/${form.dataset.openTable}/sessions`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        guest_count: Number(formData.get("guest_count")),
                        note: formData.get("note") || null,
                    }),
                },
            );
            await refreshRoom();
            await openSession(serviceSession.id, form.closest("[data-table-card]").querySelector("h2").textContent);
            showAlert("Mesa abierta.", true);
        });
    });

    roomGrid.addEventListener("click", (event) => {
        const button = event.target.closest("[data-open-session]");
        if (!button) {
            return;
        }
        withBusyButton(button, () => openSession(
            button.dataset.openSession,
            button.dataset.tableCode,
        ));
    });

    zoneFilter.addEventListener("click", (event) => {
        const button = event.target.closest("[data-zone-filter]");
        if (!button) {
            return;
        }
        zoneFilter.querySelectorAll("button").forEach((item) => {
            item.classList.toggle("is-active", item === button);
        });
        roomGrid.querySelectorAll("[data-table-card]").forEach((card) => {
            card.hidden = button.dataset.zoneFilter !== "all"
                && card.dataset.zoneId !== button.dataset.zoneFilter;
        });
    });

    document.getElementById("dishSearch").addEventListener("input", (event) => {
        const query = event.target.value.trim().toLowerCase();
        dishPicker.querySelectorAll("[data-dish-card]").forEach((card) => {
            card.hidden = query && !card.dataset.search.includes(query);
        });
    });

    dishPicker.addEventListener("click", (event) => {
        const button = event.target.closest("[data-add-dish]");
        if (!button) {
            return;
        }
        withBusyButton(button, async () => {
            const order = await currentDraftOrder();
            const note = dishPicker.querySelector(
                `[data-dish-note="${button.dataset.addDish}"]`,
            ).value.trim();
            await requestJson(
                `/api/orders/${state.restaurantId}/${order.id}/lines`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        dish_id: Number(button.dataset.addDish),
                        quantity: 1,
                        note: note || null,
                        idempotency_key: randomKey(),
                    }),
                },
            );
            await loadOrders();
            showAlert("Plato añadido.", true);
        });
    });

    orderList.addEventListener("click", (event) => {
        const button = event.target.closest("button");
        if (!button) {
            return;
        }
        const orderCard = button.closest("[data-order-id]");
        const orderId = orderCard?.dataset.orderId;

        withBusyButton(button, async () => {
            if (button.dataset.lineQuantity) {
                await requestJson(
                    `/api/orders/${state.restaurantId}/${orderId}/lines/${button.dataset.lineQuantity}`,
                    {
                        method: "PATCH",
                        body: JSON.stringify({ quantity: Number(button.dataset.quantity) }),
                    },
                );
            } else if (button.dataset.saveNote) {
                const note = orderCard.querySelector(
                    `[data-line-note="${button.dataset.saveNote}"]`,
                ).value.trim();
                await requestJson(
                    `/api/orders/${state.restaurantId}/${orderId}/lines/${button.dataset.saveNote}`,
                    {
                        method: "PATCH",
                        body: JSON.stringify({ note: note || null }),
                    },
                );
                showAlert("Observación guardada.", true);
            } else if (button.dataset.deleteLine) {
                await requestJson(
                    `/api/orders/${state.restaurantId}/${orderId}/lines/${button.dataset.deleteLine}`,
                    { method: "DELETE" },
                );
            } else if (button.dataset.submitOrder) {
                if (!window.confirm("¿Enviar este pedido? Después no podrás editarlo.")) {
                    return;
                }
                await requestJson(
                    `/api/orders/${state.restaurantId}/${orderId}/submit`,
                    { method: "POST" },
                );
                showAlert("Pedido enviado y bloqueado para edición.", true);
            } else if (button.dataset.approveCustomerOrder) {
                if (!window.confirm(
                    "¿Aceptar este pedido y enviarlo a cocina?",
                )) {
                    return;
                }
                await requestJson(
                    `/api/orders/${state.restaurantId}/${orderId}/customer-approval`,
                    {method: "POST"},
                );
                showAlert(
                    "Pedido de cliente aceptado y enviado a cocina.",
                    true,
                );
            } else if (button.dataset.rejectCustomerOrder) {
                const reason = window.prompt(
                    "Motivo opcional para el cliente:",
                    "",
                );
                if (reason === null) {
                    return;
                }
                await requestJson(
                    `/api/orders/${state.restaurantId}/${orderId}/customer-rejection`,
                    {
                        method: "POST",
                        body: JSON.stringify({
                            reason: reason.trim() || null,
                        }),
                    },
                );
                showAlert("Pedido de cliente rechazado.", true);
            } else if (button.dataset.cancelOrder) {
                if (!window.confirm("¿Cancelar este pedido?")) {
                    return;
                }
                await requestJson(
                    `/api/orders/${state.restaurantId}/${orderId}/cancel`,
                    { method: "POST" },
                );
                showAlert("Pedido cancelado.", true);
            } else if (button.dataset.fulfillOrder) {
                await requestJson(
                    `/api/orders/${state.restaurantId}/${orderId}/fulfill`,
                    { method: "POST" },
                );
                showAlert("Servicio confirmado e inventario actualizado.", true);
            }
            await loadOrders();
        });
    });

    document.getElementById("newOrderButton").addEventListener("click", (event) => {
        withBusyButton(event.currentTarget, async () => {
            if (state.orders.some((order) => order.status === "draft")) {
                showAlert("Ya existe una ronda en borrador.");
                return;
            }
            await createOrder();
            showAlert("Nueva ronda preparada.", true);
        });
    });

    document.getElementById("closeSessionWorkspace").addEventListener("click", () => {
        showRoom().catch((error) => showAlert(error.message));
    });

    const paymentMethodLabel = {
        cash: "Efectivo",
        card: "Tarjeta manual",
        other: "Otro",
    };

    const renderPaymentState = () => {
        const balance = state.paymentBalance;
        if (!balance) {
            return;
        }
        paymentTotal.textContent = formatMoney(balance.total);
        paymentPaid.textContent = formatMoney(balance.amount_paid);
        paymentRemaining.textContent = formatMoney(balance.amount_remaining);
        paymentStatus.textContent = balance.is_fully_paid
            ? "Completamente pagado"
            : "Pago pendiente";
        paymentForm.hidden = balance.is_fully_paid;
        paymentAmount.value = balance.amount_remaining;
        paymentHistory.innerHTML = state.payments.length
            ? state.payments.map((payment) => `
                <article class="payment-history-item">
                    <div>
                        <strong>${escapeHtml(paymentMethodLabel[payment.method] || payment.method)}</strong>
                        <p>${escapeHtml(payment.reference || "Sin referencia")} · ${escapeHtml(payment.paid_at)}</p>
                    </div>
                    <strong>${formatMoney(payment.amount)}</strong>
                </article>`).join("")
            : `<div class="waiter-empty"><h2>Sin pagos registrados</h2><p>El balance permanece pendiente.</p></div>`;
    };

    const loadPaymentState = async () => {
        const baseUrl = `/api/dining/${state.restaurantId}/settlements/${state.currentSettlementId}`;
        const [payments, balance] = await Promise.all([
            requestJson(`${baseUrl}/payments`),
            requestJson(`${baseUrl}/balance`),
        ]);
        state.payments = payments;
        state.paymentBalance = balance;
        renderPaymentState();
    };

    const showPaymentPanel = async (settlement) => {
        state.currentSettlementId = settlement.settlement_id;
        state.paymentIdempotencyKey = randomKey();
        sessionLayout.hidden = true;
        paymentPanel.hidden = false;
        sessionEyebrow.textContent = "Cuenta finalizada";
        sessionMeta.textContent = "La sesión está cerrada. La mesa ya está libre.";
        await loadPaymentState();
    };

    settleSessionButton.addEventListener("click", async (event) => {
        if (!window.confirm("¿Cerrar la cuenta y finalizar el servicio?")) {
            return;
        }
        await withBusyButton(event.currentTarget, async () => {
            const settlement = await requestJson(
                `/api/dining/${state.restaurantId}/sessions/${state.currentSessionId}/settle`,
                { method: "POST" },
            );
            const finalTotal = formatMoney(settlement.total);
            await showPaymentPanel(settlement);
            showAlert(`Cuenta cerrada. Total final: ${finalTotal}.`, true);
        });
    });

    paymentForm.addEventListener("input", () => {
        state.paymentIdempotencyKey = randomKey();
    });

    paymentForm.addEventListener("change", () => {
        state.paymentIdempotencyKey = randomKey();
    });

    paymentForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = document.getElementById("registerPaymentButton");
        await withBusyButton(button, async () => {
            const result = await requestJson(
                `/api/dining/${state.restaurantId}/settlements/${state.currentSettlementId}/payments`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        amount: paymentAmount.value.trim(),
                        method: paymentMethod.value,
                        currency: state.paymentBalance.currency,
                        reference: paymentReference.value.trim() || null,
                        idempotency_key: state.paymentIdempotencyKey,
                    }),
                },
            );
            if (!state.payments.some(
                (payment) => payment.payment_id === result.payment_id,
            )) {
                state.payments.push(result);
            }
            state.paymentBalance = result.balance;
            state.paymentIdempotencyKey = randomKey();
            paymentReference.value = "";
            renderPaymentState();
            showAlert("Pago registrado y balance actualizado.", true);
        });
    });

    cancelTableButton.addEventListener(
        "click",
        async (event) => {
            if (!window.confirm("¿Cancelar esta sesión de mesa?")) {
                return;
            }
            await withBusyButton(event.currentTarget, async () => {
                await requestJson(
                    `/api/dining/${state.restaurantId}/sessions/${state.currentSessionId}/cancel`,
                    { method: "POST" },
                );
                await showRoom();
                showAlert("Sesión cancelada.", true);
            });
        },
    );

    window.setInterval(() => {
        if (
            state.currentSessionId
            && !state.currentSettlementId
            && !document.hidden
        ) {
            loadOrders().catch((error) => showAlert(error.message));
        }
    }, 20000);

    renderRoom();
}
