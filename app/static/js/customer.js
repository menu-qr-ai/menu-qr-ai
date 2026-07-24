const customerRoot = document.querySelector("[data-customer-menu]");
const customerBootstrap = document.getElementById("customerBootstrap");

if (customerRoot && customerBootstrap) {
    const bootstrap = JSON.parse(customerBootstrap.textContent);
    const state = {
        ...bootstrap.state,
        sessionToken: bootstrap.sessionToken,
        categoryId: "all",
        query: "",
        busy: false,
    };
    const apiBase = `/api/customer/sessions/${encodeURIComponent(state.sessionToken)}`;
    const dishesElement = document.getElementById("customerDishes");
    const categoriesElement = document.getElementById("customerCategories");
    const linesElement = document.getElementById("customerOrderLines");
    const statusElement = document.getElementById("customerOrderStatus");
    const totalUnitsElement = document.getElementById("customerTotalUnits");
    const totalAmountElement = document.getElementById("customerTotalAmount");
    const submitButton = document.getElementById("customerSubmitOrder");
    const alertElement = document.getElementById("customerAlert");

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const randomKey = () => globalThis.crypto?.randomUUID?.()
        || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

    const formatMoney = (value) => new Intl.NumberFormat("es-ES", {
        style: "currency",
        currency: state.restaurant.currency,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(Number(value || 0));

    const requestJson = async (url, options = {}) => {
        const response = await window.fetch(url, {
            credentials: "omit",
            headers: {
                "Content-Type": "application/json",
                ...(options.headers || {}),
            },
            ...options,
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(
                payload.error?.message
                || "No se pudo completar la acción.",
            );
        }
        return payload;
    };

    const showAlert = (message, success = false) => {
        alertElement.textContent = message;
        alertElement.classList.toggle("is-success", success);
        alertElement.hidden = false;
        window.clearTimeout(showAlert.timeout);
        showAlert.timeout = window.setTimeout(() => {
            alertElement.hidden = true;
        }, 6000);
    };

    const activeOrder = () => [...state.orders].reverse().find(
        (order) => ["draft_customer", "submitted_customer"].includes(
            order.status,
        ),
    );

    const latestOrder = () => state.orders.at(-1) || null;

    const setState = (payload) => {
        Object.assign(state, payload, {
            sessionToken: state.sessionToken,
            categoryId: state.categoryId,
            query: state.query,
            busy: state.busy,
        });
    };

    const ensureDraft = async () => {
        let order = activeOrder();
        if (order?.status === "submitted_customer") {
            throw new Error(
                "El pedido está esperando la revisión del camarero.",
            );
        }
        if (!order) {
            setState(await requestJson(`${apiBase}/orders`, {
                method: "POST",
                body: JSON.stringify({
                    idempotency_key: randomKey(),
                }),
            }));
            order = activeOrder();
        }
        return order;
    };

    const renderCategories = () => {
        categoriesElement.innerHTML = [
            {id: "all", name: "Todo"},
            ...state.categories,
        ].map((category) => `
            <button
                type="button"
                class="${String(category.id) === String(state.categoryId) ? "is-active" : ""}"
                data-customer-category="${category.id}"
            >${escapeHtml(category.name)}</button>
        `).join("");
    };

    const renderDishes = () => {
        const query = state.query.toLowerCase();
        const visible = state.dishes.filter((dish) => {
            const matchesCategory = state.categoryId === "all"
                || String(dish.category_id)
                    === String(state.categoryId);
            const haystack = [
                dish.name,
                dish.description,
                dish.ingredients,
                dish.allergens,
            ].join(" ").toLowerCase();
            return matchesCategory
                && (!query || haystack.includes(query));
        });
        dishesElement.innerHTML = visible.length
            ? visible.map((dish) => `
                <article class="customer-dish ${dish.is_available ? "" : "is-unavailable"}">
                    <div class="customer-dish-heading">
                        <h3>${escapeHtml(dish.name)}</h3>
                        <span class="customer-price">${formatMoney(dish.price)}</span>
                    </div>
                    <p class="customer-description">${escapeHtml(dish.description || "Sin descripción")}</p>
                    <p class="customer-allergens"><strong>Alérgenos:</strong> ${escapeHtml(dish.allergens || "No informados")}</p>
                    <p class="customer-availability">${escapeHtml(dish.availability_label)}</p>
                    <input
                        class="customer-dish-note"
                        data-customer-note="${dish.id}"
                        type="text"
                        maxlength="1000"
                        placeholder="Observación: sin cebolla…"
                        ${dish.is_available ? "" : "disabled"}
                    >
                    <button
                        class="customer-primary"
                        type="button"
                        data-customer-add="${dish.id}"
                        ${dish.is_available ? "" : "disabled"}
                    >Añadir al pedido</button>
                </article>
            `).join("")
            : `<p class="customer-empty">No hay platos que coincidan con la búsqueda.</p>`;
    };

    const statusLabels = {
        draft_customer: "Preparando",
        submitted_customer: "Esperando camarero",
        submitted: "Aceptado",
        cancelled: "Rechazado",
        completed: "Completado",
    };

    const renderOrder = () => {
        const order = activeOrder() || latestOrder();
        if (!order) {
            statusElement.textContent = "Nuevo";
            linesElement.innerHTML = `
                <p class="customer-empty">Añade platos para preparar tu pedido.</p>
            `;
            totalUnitsElement.textContent = "0 platos";
            totalAmountElement.textContent = formatMoney("0.00");
            submitButton.disabled = true;
            submitButton.hidden = false;
            return;
        }
        const editable = order.status === "draft_customer";
        statusElement.textContent = (
            statusLabels[order.status] || order.status
        );
        linesElement.innerHTML = order.lines.length
            ? order.lines.map((line) => `
                <article class="customer-order-line">
                    <div class="customer-line-heading">
                        <strong>${escapeHtml(line.dish_name)}</strong>
                        <span>${formatMoney(line.subtotal)}</span>
                    </div>
                    <p>${escapeHtml(line.note || "Sin observaciones")}</p>
                    ${editable ? `
                        <div class="customer-line-controls">
                            <button
                                class="customer-quantity-button"
                                type="button"
                                data-customer-quantity="${line.id}"
                                data-next-quantity="${line.quantity - 1}"
                                ${line.quantity <= 1 ? "disabled" : ""}
                                aria-label="Restar unidad"
                            >−</button>
                            <strong>${line.quantity}</strong>
                            <button
                                class="customer-quantity-button"
                                type="button"
                                data-customer-quantity="${line.id}"
                                data-next-quantity="${line.quantity + 1}"
                                aria-label="Añadir unidad"
                            >+</button>
                            <button
                                class="customer-quantity-button customer-remove"
                                type="button"
                                data-customer-remove="${line.id}"
                                aria-label="Eliminar ${escapeHtml(line.dish_name)}"
                            >×</button>
                        </div>
                    ` : ""}
                </article>
            `).join("")
            : `<p class="customer-empty">Añade el primer plato.</p>`;
        totalUnitsElement.textContent = (
            `${order.total_units} `
            + (order.total_units === 1 ? "plato" : "platos")
        );
        totalAmountElement.textContent = formatMoney(
            order.total_amount,
        );
        submitButton.hidden = !editable;
        submitButton.disabled = !editable || !order.lines.length;
        if (order.status === "submitted_customer") {
            linesElement.insertAdjacentHTML(
                "beforeend",
                "<p class=\"customer-empty\">El camarero revisará disponibilidad y observaciones antes de enviarlo a cocina.</p>",
            );
        } else if (order.status === "submitted") {
            linesElement.insertAdjacentHTML(
                "beforeend",
                "<p class=\"customer-empty\">Pedido aceptado. Ya ha entrado en el flujo del restaurante.</p>",
            );
        } else if (order.status === "cancelled") {
            linesElement.insertAdjacentHTML(
                "beforeend",
                `<p class="customer-empty">${escapeHtml(
                    order.rejection_reason
                    || "El camarero no pudo aceptar este pedido.",
                )}</p>`,
            );
        }
    };

    const render = () => {
        renderCategories();
        renderDishes();
        renderOrder();
        customerRoot.querySelectorAll("button").forEach((button) => {
            if (state.busy) {
                button.disabled = true;
            }
        });
    };

    const withBusy = async (callback) => {
        if (state.busy) {
            return;
        }
        state.busy = true;
        render();
        try {
            await callback();
        } catch (error) {
            showAlert(error.message);
        } finally {
            state.busy = false;
            render();
        }
    };

    document.getElementById("customerSearch").addEventListener(
        "input",
        (event) => {
            state.query = event.target.value.trim();
            renderDishes();
        },
    );

    categoriesElement.addEventListener("click", (event) => {
        const button = event.target.closest(
            "[data-customer-category]",
        );
        if (!button) {
            return;
        }
        state.categoryId = button.dataset.customerCategory;
        renderCategories();
        renderDishes();
    });

    dishesElement.addEventListener("click", (event) => {
        const button = event.target.closest("[data-customer-add]");
        if (!button) {
            return;
        }
        const dishId = button.dataset.customerAdd;
        const note = dishesElement.querySelector(
            `[data-customer-note="${dishId}"]`,
        ).value.trim();
        withBusy(async () => {
            await ensureDraft();
            setState(await requestJson(`${apiBase}/order/lines`, {
                method: "POST",
                body: JSON.stringify({
                    dish_id: Number(dishId),
                    quantity: 1,
                    note: note || null,
                    idempotency_key: randomKey(),
                }),
            }));
            showAlert("Plato añadido.", true);
        });
    });

    linesElement.addEventListener("click", (event) => {
        const quantityButton = event.target.closest(
            "[data-customer-quantity]",
        );
        const removeButton = event.target.closest(
            "[data-customer-remove]",
        );
        if (!quantityButton && !removeButton) {
            return;
        }
        withBusy(async () => {
            if (quantityButton) {
                setState(await requestJson(
                    `${apiBase}/order/lines/${quantityButton.dataset.customerQuantity}`,
                    {
                        method: "PATCH",
                        body: JSON.stringify({
                            quantity: Number(
                                quantityButton.dataset.nextQuantity,
                            ),
                        }),
                    },
                ));
            } else {
                setState(await requestJson(
                    `${apiBase}/order/lines/${removeButton.dataset.customerRemove}`,
                    {method: "DELETE"},
                ));
            }
        });
    });

    submitButton.addEventListener("click", () => {
        if (!window.confirm(
            "¿Enviar este pedido al camarero para que lo revise?",
        )) {
            return;
        }
        withBusy(async () => {
            setState(await requestJson(
                `${apiBase}/order/submit`,
                {method: "POST"},
            ));
            showAlert("Pedido enviado al camarero.", true);
        });
    });

    window.setInterval(async () => {
        if (
            document.hidden
            || activeOrder()?.status !== "submitted_customer"
        ) {
            return;
        }
        try {
            setState(await requestJson(apiBase));
            render();
        } catch (error) {
            showAlert(error.message);
        }
    }, 10000);

    render();
}
