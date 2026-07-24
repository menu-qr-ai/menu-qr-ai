const kitchenWorkspace = document.querySelector("[data-kitchen-workspace]");
const kitchenBootstrapElement = document.getElementById("kitchenBootstrap");

if (kitchenWorkspace && kitchenBootstrapElement) {
    const state = {
        ...JSON.parse(kitchenBootstrapElement.textContent),
        currentFilter: "active",
    };

    const grid = document.getElementById("kitchenGrid");
    const filters = document.querySelector(".kitchen-filters");
    const alertBox = document.getElementById("kitchenAlert");
    const updatedAt = document.getElementById("kitchenUpdatedAt");
    const refreshButton = document.getElementById("refreshKitchen");

    const escapeHtml = (value) => String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

    const statusLabel = {
        pending: "Pendiente",
        preparing: "En preparación",
        ready: "Lista",
        served: "Servida",
        cancelled: "Cancelada",
    };

    const relativeTime = (createdAt) => {
        const elapsed = Math.max(0, Date.now() - new Date(createdAt).getTime());
        const minutes = Math.floor(elapsed / 60000);
        if (minutes < 1) {
            return "ahora";
        }
        if (minutes < 60) {
            return `hace ${minutes} min`;
        }
        const hours = Math.floor(minutes / 60);
        return `hace ${hours} h ${minutes % 60} min`;
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
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error?.message || "No se pudo completar la acción.");
        }
        return payload;
    };

    const lineActions = (ticket, line) => {
        if (ticket.status === "ready") {
            return "";
        }
        if (line.status === "pending") {
            return `
                <div class="line-actions">
                    <button class="line-action-button" type="button" data-line-action="start" data-line-id="${line.id}">Iniciar</button>
                    <button class="line-action-button" type="button" data-line-action="cancel" data-line-id="${line.id}">Cancelar</button>
                </div>`;
        }
        if (line.status === "preparing") {
            return `
                <div class="line-actions">
                    <button class="line-action-button" type="button" data-line-action="ready" data-line-id="${line.id}">Lista</button>
                    <button class="line-action-button" type="button" data-line-action="cancel" data-line-id="${line.id}">Cancelar</button>
                </div>`;
        }
        return "";
    };

    const lineHtml = (ticket, line) => `
        <div class="ticket-line is-${line.status}">
            <div>
                <strong>${line.quantity}× ${escapeHtml(line.dish_name)}</strong>
                ${line.note ? `<p class="ticket-note">${escapeHtml(line.note)}</p>` : ""}
                ${line.current_allergens
                    ? `<p class="ticket-allergens">Alérgenos: ${escapeHtml(line.current_allergens)}</p>`
                    : ""}
            </div>
            ${lineActions(ticket, line) || `<span>${statusLabel[line.status]}</span>`}
        </div>`;

    const ticketActions = (ticket) => {
        if (ticket.status === "pending") {
            return `
                <button class="kitchen-primary-button" type="button" data-ticket-action="start">Iniciar comanda</button>
                <button class="kitchen-danger-button" type="button" data-ticket-action="cancel">Cancelar</button>`;
        }
        if (ticket.status === "preparing") {
            return `
                <button class="kitchen-primary-button" type="button" data-ticket-action="ready">Marcar lista</button>
                <button class="kitchen-danger-button" type="button" data-ticket-action="cancel">Cancelar</button>`;
        }
        if (ticket.status === "ready") {
            return `<button class="kitchen-primary-button" type="button" data-ticket-action="serve">Marcar servida</button>`;
        }
        return "";
    };

    const ticketHtml = (ticket) => `
        <article class="kitchen-ticket is-${ticket.status}" data-ticket-id="${ticket.id}" data-ticket-status="${ticket.status}">
            <header class="ticket-header">
                <div>
                    <span class="ticket-status">${statusLabel[ticket.status]}</span>
                    <h2>Mesa ${escapeHtml(ticket.table_code)}</h2>
                    <p>${escapeHtml(ticket.zone_name || "Sin zona")} · Pedido #${ticket.order_id}</p>
                </div>
                <time datetime="${ticket.created_at}">${relativeTime(ticket.created_at)}</time>
            </header>
            <div class="ticket-lines">
                ${ticket.lines.map((line) => lineHtml(ticket, line)).join("")}
            </div>
            <div class="ticket-actions">${ticketActions(ticket)}</div>
        </article>`;

    const render = () => {
        grid.innerHTML = state.tickets.length
            ? state.tickets.map(ticketHtml).join("")
            : `<div class="kitchen-empty"><h2>Sin comandas activas</h2><p>Los pedidos enviados desde sala aparecerán aquí.</p></div>`;
        updatedAt.textContent = `Actualizado ${new Date().toLocaleTimeString("es-ES", {
            hour: "2-digit",
            minute: "2-digit",
        })}`;
    };

    const loadTickets = async () => {
        const query = state.currentFilter === "active"
            ? "?active_only=true"
            : `?status=${encodeURIComponent(state.currentFilter)}`;
        state.tickets = await requestJson(
            `/api/kitchen/${state.restaurantId}/tickets${query}`,
        );
        render();
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
            await loadTickets().catch(() => {});
        } finally {
            button.disabled = false;
        }
    };

    filters.addEventListener("click", (event) => {
        const button = event.target.closest("[data-ticket-filter]");
        if (!button) {
            return;
        }
        state.currentFilter = button.dataset.ticketFilter;
        filters.querySelectorAll("button").forEach((item) => {
            item.classList.toggle("is-active", item === button);
        });
        withBusyButton(button, loadTickets);
    });

    refreshButton.addEventListener("click", () => {
        withBusyButton(refreshButton, async () => {
            await loadTickets();
            showAlert("Comandas actualizadas.", true);
        });
    });

    grid.addEventListener("click", (event) => {
        const button = event.target.closest("button");
        const ticketCard = button?.closest("[data-ticket-id]");
        if (!button || !ticketCard) {
            return;
        }
        const ticketId = ticketCard.dataset.ticketId;
        const ticketAction = button.dataset.ticketAction;
        const lineAction = button.dataset.lineAction;
        const lineId = button.dataset.lineId;
        const action = ticketAction || lineAction;
        if (action === "cancel" && !window.confirm("¿Cancelar este elemento de cocina?")) {
            return;
        }

        withBusyButton(button, async () => {
            const path = lineAction
                ? `/api/kitchen/${state.restaurantId}/tickets/${ticketId}/lines/${lineId}/${lineAction}`
                : `/api/kitchen/${state.restaurantId}/tickets/${ticketId}/${ticketAction}`;
            await requestJson(path, { method: "POST" });
            await loadTickets();
            showAlert("Estado de cocina actualizado.", true);
        });
    });

    window.setInterval(() => {
        if (!document.hidden) {
            loadTickets().catch((error) => showAlert(error.message));
        }
    }, state.pollIntervalMs);

    render();
}
