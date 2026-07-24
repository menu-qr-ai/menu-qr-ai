const dashboardRoot = document.querySelector(".dashboard-shell");
const dashboardState = document.getElementById("dashboardState");
const dashboardMeta = document.getElementById("dashboardMeta");
const dashboardUpdatedAt = document.getElementById("dashboardUpdatedAt");
const demoSeedCta = document.getElementById("demoSeedCta");
const refreshButton = document.getElementById("refreshDashboard");
const restaurantSelect = document.getElementById("restaurantSelect");
const rangeButtons = Array.from(document.querySelectorAll("[data-range-option]"));
const predictionConfidence = document.getElementById("predictionConfidence");

let activeRange = dashboardRoot?.dataset.range || "30d";

function numberFormat(value) {
    return new Intl.NumberFormat("es-ES").format(Number(value || 0));
}

function showState(message, visible = true, tone = "neutral") {
    if (!dashboardState) {
        return;
    }
    dashboardState.textContent = message;
    dashboardState.dataset.tone = tone;
    dashboardState.classList.toggle("is-visible", visible);
}

function setLoading(isLoading) {
    dashboardRoot?.classList.toggle("is-loading", isLoading);
    if (refreshButton) {
        refreshButton.disabled = isLoading;
    }
}

function setActiveRange(range) {
    activeRange = range;
    rangeButtons.forEach((button) => {
        const isActive = button.dataset.rangeOption === range;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
    });
}

function setKpis(summary) {
    Object.entries(summary).forEach(([key, value]) => {
        const node = document.querySelector(`[data-kpi="${key}"]`);
        if (!node) {
            return;
        }
        node.textContent = typeof value === "number" ? numberFormat(value) : value || "Sin datos";
    });
}

function emptyRow(message) {
    const element = document.createElement("div");
    element.className = "empty-row";
    element.textContent = message;
    return element;
}

function emptyState(titleText, messageText, tone = "opportunity") {
    const element = document.createElement("article");
    element.className = `empty-state ${tone}`;
    const title = document.createElement("strong");
    title.textContent = titleText;
    const message = document.createElement("p");
    message.textContent = messageText;
    element.append(title, message);
    return element;
}

function badge(text) {
    const element = document.createElement("span");
    element.className = "metric-badge";
    element.textContent = text;
    return element;
}

function metricRow(label, value, detail = "", badgeText = "") {
    const row = document.createElement("div");
    row.className = "metric-row";

    const copy = document.createElement("div");
    const labelNode = document.createElement("div");
    labelNode.className = "metric-value";
    labelNode.textContent = label;
    const detailNode = document.createElement("div");
    detailNode.className = "metric-label";
    detailNode.textContent = detail;
    copy.append(labelNode, detailNode);

    const valueWrap = document.createElement("div");
    valueWrap.className = "metric-side";
    const valueNode = document.createElement("strong");
    valueNode.className = "metric-value";
    valueNode.textContent = numberFormat(value);
    valueWrap.appendChild(valueNode);
    if (badgeText) {
        valueWrap.appendChild(badge(badgeText));
    }

    row.append(copy, valueWrap);
    return row;
}

function renderMetricList(containerId, items, emptyMessage, mapper) {
    const container = document.getElementById(containerId);
    if (!container) {
        return;
    }
    container.replaceChildren();
    if (!items.length) {
        container.appendChild(emptyRow(emptyMessage));
        return;
    }
    items.forEach((item) => container.appendChild(mapper(item)));
}

function renderRecentEvents(events) {
    const container = document.getElementById("recentEvents");
    if (!container) {
        return;
    }
    container.replaceChildren();
    if (!events.length) {
        container.appendChild(emptyRow("Todavia no hay actividad reciente."));
        return;
    }
    events.forEach((event) => {
        const row = document.createElement("div");
        row.className = "event-row";

        const copy = document.createElement("div");
        const type = document.createElement("div");
        type.className = "event-type";
        type.textContent = event.event_type;
        const meta = document.createElement("div");
        meta.className = "event-meta";
        meta.textContent = [
            event.language ? `Idioma ${event.language}` : "",
            event.dish_id ? `Plato #${event.dish_id}` : "",
        ].filter(Boolean).join(" - ") || "Evento general";
        copy.append(type, meta);

        const time = document.createElement("time");
        time.className = "event-meta";
        time.dateTime = event.created_at;
        time.textContent = new Date(event.created_at).toLocaleString("es-ES");

        row.append(copy, time);
        container.appendChild(row);
    });
}

function renderInsights(insights) {
    const container = document.getElementById("insights");
    if (!container) {
        return;
    }
    container.replaceChildren();
    insights.forEach((insight) => {
        const card = document.createElement("article");
        card.className = `insight-card ${insight.level || "info"}`;
        const title = document.createElement("strong");
        title.textContent = insight.title;
        const message = document.createElement("p");
        message.textContent = insight.message;
        card.append(title, message);
        container.appendChild(card);
    });
}

function insightCard(titleText, messageText, level = "info") {
    const card = document.createElement("article");
    card.className = `insight-card ${normalizeSeverity(level)}`;
    const title = document.createElement("strong");
    title.textContent = titleText;
    const message = document.createElement("p");
    message.textContent = messageText;
    card.append(title, message);
    return card;
}

function normalizeSeverity(level = "info") {
    const normalized = String(level || "info").toLowerCase();
    if (["critical", "warning", "healthy", "opportunity"].includes(normalized)) {
        return normalized;
    }
    if (normalized === "success") {
        return "healthy";
    }
    if (normalized === "low") {
        return "warning";
    }
    if (normalized === "high" || normalized === "danger") {
        return "critical";
    }
    if (normalized === "medium" || normalized === "info") {
        return "opportunity";
    }
    return "opportunity";
}

function setInventoryKpis(status) {
    if (!status) {
        return;
    }
    Object.entries(status).forEach(([key, value]) => {
        const node = document.querySelector(`[data-inventory-kpi="${key}"]`);
        if (node) {
            node.textContent = key === "inventory_health_percentage" ? `${Number(value || 0).toFixed(0)}%` : numberFormat(value);
        }
    });
}

function renderInventoryCards(containerId, items, emptyMessage, mapper) {
    const container = document.getElementById(containerId);
    if (!container) {
        return;
    }
    container.replaceChildren();
    if (!items.length) {
        container.appendChild(emptyMessage);
        return;
    }
    items.forEach((item) => container.appendChild(mapper(item)));
}

function inventoryEmptyStates(overview) {
    if (!overview.total_items) {
        return {
            alerts: emptyState(
                "Inventario pendiente",
                "Anade ingredientes y stock inicial para ver riesgos de compra antes del servicio.",
            ),
            actions: emptyState(
                "Aun no hay motor operativo",
                "Cuando exista inventario, HostAI podra priorizar compras y preparacion sin convertirlo en un CRUD.",
            ),
            risk: emptyState(
                "Sin platos en riesgo",
                "El riesgo aparece al conectar ingredientes con platos reales.",
            ),
            critical: emptyState(
                "Sin ingredientes que vigilar",
                "Carga stock minimo e ideal para medir salud operativa.",
            ),
        };
    }
    if (overview.insights.some((insight) => insight.insight_type === "dish_ingredient_setup")) {
        return {
            alerts: emptyState("Sin alertas activas", "El stock existe, pero falta conectar ingredientes con platos para anticipar impacto.", "healthy"),
            actions: emptyState("Falta mapa de recetas", "Conecta platos e ingredientes para desbloquear compras prioritarias y platos en riesgo."),
            risk: emptyState("Riesgo no calculable", "HostAI necesita saber que ingredientes usa cada plato para anticipar agotados."),
            critical: emptyState("Sin criticos por receta", "Los ingredientes criticos apareceran aqui cuando tengan impacto en platos.", "healthy"),
        };
    }
    if (overview.insights.some((insight) => insight.insight_type === "analytics_needed")) {
        return {
            alerts: emptyState("Inventario conectado", "No hay alertas fuertes. Falta demanda real para priorizar con seguridad.", "healthy"),
            actions: emptyState("Esperando demanda", "Cuando los clientes vean platos, Operaciones cruzara interes real con stock."),
            risk: emptyState("Sin demanda suficiente", "Los platos en riesgo se ordenan por visitas reales y stock critico."),
            critical: emptyState("Stock bajo sin lectura comercial", "Puede haber stock bajo, pero aun falta demanda para priorizarlo.", "warning"),
        };
    }
    return {
        alerts: emptyState("Sin alertas activas", "El inventario no muestra roturas ni umbrales criticos ahora mismo.", "healthy"),
        actions: emptyState("Sin acciones urgentes", "Mantener seguimiento. Las recomendaciones apareceran al detectar demanda, stock bajo o riesgo de desperdicio.", "healthy"),
        risk: emptyState("Sin platos en riesgo", "Ningun plato combina demanda visible con ingredientes criticos.", "healthy"),
        critical: emptyState("Sin ingredientes criticos", "Los niveles actuales estan dentro de una zona operativa razonable.", "healthy"),
    };
}

function renderInventory(overview) {
    const emptyStates = inventoryEmptyStates(overview);
    setInventoryKpis(overview.status);
    renderInventoryCards("inventoryAlerts", overview.alerts, emptyStates.alerts, (alert) =>
        insightCard(alert.title, alert.message, alert.severity),
    );
    const actionable = overview.recommended_actions.filter((action) => action.action_type !== "no_action");
    renderInventoryCards("inventoryActions", actionable, emptyStates.actions, (action) =>
        insightCard(action.title, action.message, action.priority || "info"),
    );
    renderInventoryCards("dishesAtRisk", overview.dishes_at_risk, emptyStates.risk, (dish) =>
        metricRow(
            dish.name,
            dish.views,
            `Ingredientes a vigilar: ${dish.critical_ingredients.join(", ")}`,
            "vistas",
        ),
    );
    renderInventoryCards("criticalItems", overview.top_critical_items, emptyStates.critical, (item) =>
        metricRow(
            item.name,
            item.current_stock,
            `Minimo ${numberFormat(item.minimum_stock)} ${item.unit}`,
            item.unit,
        ),
    );
}

function predictionEmptyStates(overview) {
    if (overview.confidence_level === "low") {
        return {
            dishes: emptyState("Demanda aun poco fiable", overview.explanation),
            ingredients: emptyState("Consumo no proyectable", overview.explanation),
            prep: emptyState("Preparacion sin prioridad clara", "HostAI necesita mas demanda real y recetas conectadas para recomendar preparacion con seguridad."),
            purchases: emptyState("Compras sin prediccion fuerte", "Las compras predictivas apareceran cuando haya demanda reciente y riesgo de stock."),
        };
    }
    return {
        dishes: emptyState("Sin platos destacados", "No hay platos con demanda probable por encima del resto en este rango.", "healthy"),
        ingredients: emptyState("Sin bajadas previstas", "No hay ingredientes con presion de demanda y stock bajo.", "healthy"),
        prep: emptyState("Sin preparacion extra", "La demanda prevista no exige preparar mas unidades ahora mismo.", "healthy"),
        purchases: emptyState("Sin compras predictivas", "No hay ingredientes que combinen demanda alta y stock en riesgo.", "healthy"),
    };
}

function renderPrediction(overview) {
    const emptyStates = predictionEmptyStates(overview);
    if (predictionConfidence) {
        predictionConfidence.textContent = `Confianza ${overview.confidence_level}`;
        predictionConfidence.className = `dashboard-badge ${normalizeSeverity(overview.confidence_level)}`;
    }
    renderInventoryCards("predictionDishes", overview.dishes_likely_to_sell, emptyStates.dishes, (dish) =>
        metricRow(dish.name, dish.recent_views, dish.explanation, dish.demand_level),
    );
    renderInventoryCards("predictionIngredients", overview.ingredients_likely_to_run_low, emptyStates.ingredients, (item) =>
        metricRow(item.name, item.demand_pressure, item.explanation, item.risk_level),
    );
    renderInventoryCards("predictionPrep", overview.preparation_recommendations, emptyStates.prep, (item) =>
        insightCard(item.name, item.reason, item.priority),
    );
    renderInventoryCards("predictionPurchases", overview.purchase_recommendations, emptyStates.purchases, (item) =>
        insightCard(item.name, item.reason, item.priority),
    );
}

function renderMiniBars(containerId, items, valueKey, labelKey) {
    const container = document.getElementById(containerId);
    if (!container) {
        return;
    }
    container.replaceChildren();
    const max = Math.max(...items.map((item) => Number(item[valueKey] || 0)), 1);
    if (!items.length) {
        container.appendChild(emptyRow("Sin datos para graficar."));
        return;
    }
    items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "chart-bar";
        const label = document.createElement("span");
        label.textContent = item[labelKey];
        const bar = document.createElement("i");
        bar.style.width = `${Math.max((Number(item[valueKey] || 0) / max) * 100, 4)}%`;
        const value = document.createElement("strong");
        value.textContent = numberFormat(item[valueKey]);
        row.append(label, bar, value);
        container.appendChild(row);
    });
}

function renderViewsChart(data) {
    window.dashboardCharts = window.dashboardCharts || {};
    window.dashboardCharts.views = data.events_by_day;
    renderMiniBars("viewsChart", data.events_by_day, "total_events", "date");
}

function renderLanguagesChart(data) {
    window.dashboardCharts = window.dashboardCharts || {};
    window.dashboardCharts.languages = data.languages;
    renderMiniBars("languagesChart", data.languages, "count", "language");
}

function renderTopDishesChart(data) {
    window.dashboardCharts = window.dashboardCharts || {};
    window.dashboardCharts.topDishes = data.top_dishes;
    renderMiniBars("topDishesChart", data.top_dishes, "views", "name");
}

function renderDashboard(data) {
    setKpis(data.summary);
    const totalEvents = data.events_by_day.reduce((total, day) => total + day.total_events, 0);
    if (dashboardMeta) {
        dashboardMeta.textContent = `Rango: ${data.range} - Eventos: ${numberFormat(totalEvents)}`;
    }
    if (dashboardUpdatedAt) {
        dashboardUpdatedAt.textContent = `Actualizado ${new Date().toLocaleString("es-ES")}`;
    }
    if (demoSeedCta) {
        demoSeedCta.hidden = totalEvents > 0;
    }
    renderMetricList("topDishes", data.top_dishes, "Todavia no hay platos vistos.", (dish) =>
        metricRow(dish.name, dish.views, dish.dish_id ? `ID ${dish.dish_id}` : "Sin plato asociado"),
    );
    renderMetricList("topSearches", data.top_searches, "Todavia no hay busquedas.", (search) =>
        metricRow(search.query, search.count, "busqueda registrada"),
    );
    renderMetricList("languages", data.languages, "Todavia no hay idiomas registrados.", (language) =>
        metricRow(language.language, language.count, "eventos con idioma", `${language.percentage}%`),
    );
    renderRecentEvents(data.recent_events);
    renderInsights(data.insights);
    renderViewsChart(data);
    renderLanguagesChart(data);
    renderTopDishesChart(data);
}

async function loadDashboard(range = activeRange) {
    const restaurantId = restaurantSelect ? restaurantSelect.value : dashboardRoot?.dataset.restaurantId;
    const params = new URLSearchParams();
    if (restaurantId) {
        params.set("restaurant_id", restaurantId);
    }
    params.set("range", range);
    const url = `/api/dashboard/summary?${params}`;

    try {
        setLoading(true);
        showState("Cargando datos reales...");
        const response = await window.HostAISecurity.fetch(url);
        if (!response.ok) {
            throw new Error("Dashboard request failed");
        }
        const data = await response.json();
        setActiveRange(data.range);
        renderDashboard(data);
        showState("", false);
    } catch {
        showState("No se pudieron cargar las metricas del dashboard.", true, "error");
    } finally {
        setLoading(false);
    }
}

async function loadInventory(range = activeRange) {
    const restaurantId = restaurantSelect ? restaurantSelect.value : dashboardRoot?.dataset.restaurantId;
    const params = new URLSearchParams();
    if (restaurantId) {
        params.set("restaurant_id", restaurantId);
    }
    params.set("range", range);

    try {
        const response = await window.HostAISecurity.fetch(`/api/inventory/overview?${params}`);
        if (!response.ok) {
            throw new Error("Inventory request failed");
        }
        renderInventory(await response.json());
    } catch {
        const loadError = emptyState("Operaciones no disponible", "No se pudo cargar la lectura operativa. Intentalo de nuevo en unos segundos.", "warning");
        renderInventoryCards("inventoryAlerts", [], loadError, () => null);
        renderInventoryCards("inventoryActions", [], loadError.cloneNode(true), () => null);
        renderInventoryCards("dishesAtRisk", [], loadError.cloneNode(true), () => null);
        renderInventoryCards("criticalItems", [], loadError.cloneNode(true), () => null);
    }
}

async function loadPrediction(range = activeRange) {
    const restaurantId = restaurantSelect ? restaurantSelect.value : dashboardRoot?.dataset.restaurantId;
    const params = new URLSearchParams();
    if (restaurantId) {
        params.set("restaurant_id", restaurantId);
    }
    params.set("range", range);

    try {
        const response = await window.HostAISecurity.fetch(`/api/predictions/overview?${params}`);
        if (!response.ok) {
            throw new Error("Prediction request failed");
        }
        renderPrediction(await response.json());
    } catch {
        const loadError = emptyState("Prediccion no disponible", "No se pudo cargar la prediccion operativa. Intentalo de nuevo en unos segundos.", "warning");
        renderInventoryCards("predictionDishes", [], loadError, () => null);
        renderInventoryCards("predictionIngredients", [], loadError.cloneNode(true), () => null);
        renderInventoryCards("predictionPrep", [], loadError.cloneNode(true), () => null);
        renderInventoryCards("predictionPurchases", [], loadError.cloneNode(true), () => null);
    }
}

rangeButtons.forEach((button) => {
    button.addEventListener("click", () => {
        loadDashboard(button.dataset.rangeOption);
        loadInventory(button.dataset.rangeOption);
        loadPrediction(button.dataset.rangeOption);
    });
});

refreshButton?.addEventListener("click", () => {
    loadDashboard(activeRange);
    loadInventory(activeRange);
    loadPrediction(activeRange);
});

restaurantSelect?.addEventListener("change", async () => {
    restaurantSelect.disabled = true;
    try {
        const response = await window.HostAISecurity.fetch("/api/access/active-restaurant", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({restaurant_id: Number(restaurantSelect.value)}),
        });
        if (!response.ok) {
            throw new Error("Restaurant switch failed");
        }
        window.location.assign(`/admin/dashboard?restaurant_id=${restaurantSelect.value}`);
    } catch {
        restaurantSelect.disabled = false;
        showState("No se pudo cambiar de local. Revisa tu acceso.", true, "error");
    }
});

setActiveRange(activeRange);
loadDashboard(activeRange);
loadInventory(activeRange);
loadPrediction(activeRange);
